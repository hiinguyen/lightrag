/**
 * businessApi.js — the only network layer the B2B portal uses.
 *
 * Kept separate from src/utils/api.js on purpose:
 *
 * - It stores the customer token under its own key. api.js and AuthContext use
 *   `docvault_token`; sharing that key would let a portal login overwrite an
 *   employee's session on the same machine, and would let VITE_SKIP_AUTH sign a
 *   fake Admin into a customer-facing surface.
 * - Every path is built from BUSINESS_BASE, so this module cannot address an
 *   internal endpoint at all.
 * - It unwraps the {data, meta} envelope that /business/* returns, so callers
 *   never handle two response shapes.
 */
import { resolveApiBase } from '../utils/apiBase';
// A pure SSE parser: reads a Response body, touches no storage. Shared rather
// than duplicated so the two chat surfaces cannot drift on framing.
import { readSSEStream } from '../utils/api';

const TOKEN_KEY = 'micco_business_token';
const BUSINESS_BASE = '/api/v1/business';

export class BusinessApiError extends Error {
    constructor(message, status) {
        super(message);
        this.name = 'BusinessApiError';
        this.status = status;
    }
}

// ─── Token ──────────────────────────────────────────────────────────────────

export function getBusinessToken() {
    try {
        return localStorage.getItem(TOKEN_KEY);
    } catch {
        return null;
    }
}

export function setBusinessToken(token) {
    try {
        localStorage.setItem(TOKEN_KEY, token);
    } catch { /* private mode — the session just won't survive a reload */ }
}

export function clearBusinessToken() {
    try {
        localStorage.removeItem(TOKEN_KEY);
    } catch { /* nothing to clear */ }
}

// ─── Requests ───────────────────────────────────────────────────────────────

function businessUrl(path) {
    return `${resolveApiBase()}${BUSINESS_BASE}${path}`;
}

function authHeaders(token) {
    return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request(path, { method = 'GET', body, auth = true } = {}) {
    const token = auth ? getBusinessToken() : null;

    const response = await fetch(businessUrl(path), {
        method,
        headers: {
            'Content-Type': 'application/json',
            ...authHeaders(token),
        },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });

    const payload = await response.json().catch(() => null);

    if (!response.ok) {
        // A rejected token is dead: drop it so the portal falls back to login
        // instead of retrying with it. Login failures keep whatever is stored.
        if (auth && (response.status === 401 || response.status === 403)) {
            clearBusinessToken();
        }
        throw new BusinessApiError(
            payload?.detail || payload?.error?.message || `HTTP ${response.status}`,
            response.status,
        );
    }

    return payload?.data;
}

export const businessAuthApi = {
    /** POST /auth/login → {access_token, token_type, user} */
    login: (email, password) =>
        request('/auth/login', { method: 'POST', body: { email, password }, auth: false }),

    /** GET /me → the signed-in customer's profile */
    me: () => request('/me'),
};

export const businessChatApi = {
    /** GET /chat/history → {messages, total} */
    history: () => request('/chat/history'),

    /** DELETE /chat/history → {deleted} */
    clearHistory: () => request('/chat/history', { method: 'DELETE' }),

    /** POST /leads → {id, created_at} — confirm a chat-proposed lead draft */
    createLead: (summary, packageIds) =>
        request('/leads', { method: 'POST', body: { summary, package_ids: packageIds } }),
};

/**
 * Stream one answer from POST /chat/stream.
 *
 * The request body carries only the message — the server owns the workspace,
 * the document scope and the history, so there is nothing else to send.
 *
 * @param {string} message
 * @param {object} handlers onStatus, onSources, onDelta, onRecommendations,
 *   onComplete, onError
 * @returns {Promise<void>} resolves when the stream ends
 */
export async function streamBusinessChat(message, handlers = {}) {
    const {
        onStatus, onSources, onDelta, onRecommendations, onLeadPrompt, onComplete, onError,
    } = handlers;

    let response;
    try {
        response = await fetch(businessUrl('/chat/stream'), {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...authHeaders(getBusinessToken()),
            },
            body: JSON.stringify({ message }),
        });
    } catch {
        onError?.(new BusinessApiError('Không thể kết nối máy chủ', 0));
        return;
    }

    if (!response.ok) {
        if (response.status === 401 || response.status === 403) {
            clearBusinessToken();
        }
        const payload = await response.json().catch(() => null);
        onError?.(new BusinessApiError(
            payload?.detail || `HTTP ${response.status}`,
            response.status,
        ));
        return;
    }

    await new Promise((resolve) => {
        readSSEStream(response, {
            onChunk: (chunk) => {
                switch (chunk.event) {
                    case 'status':
                        onStatus?.(chunk.detail || '');
                        break;
                    case 'sources':
                        onSources?.(chunk.sources || []);
                        break;
                    case 'delta':
                        onDelta?.(chunk.text || '');
                        break;
                    case 'recommendations':
                        onRecommendations?.(chunk.packages || []);
                        break;
                    case 'complete':
                        onComplete?.(chunk);
                        break;
                    case 'error':
                        onError?.(new BusinessApiError(chunk.message || 'Đã xảy ra lỗi', 0));
                        break;
                    case 'lead_prompt':
                        onLeadPrompt?.({ summary: chunk.summary || '', packages: chunk.packages || [] });
                        break;
                    default:
                        // Unknown events are ignored, never shown.
                        break;
                }
            },
            onDone: resolve,
            onError: (error) => {
                onError?.(error);
                resolve();
            },
        });
    });
}
