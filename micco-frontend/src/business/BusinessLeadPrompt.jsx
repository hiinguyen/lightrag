/**
 * Confirmation card for a chat-proposed lead (Phase 5).
 *
 * Not auto-submitted: the model only proposes — see BUSINESS_SYSTEM_PROMPT's
 * [[LEAD:...]] contract — and this component is the one place the customer
 * turns that proposal into a real request, via businessChatApi.createLead.
 * The draft itself is never persisted server-side, so this component's local
 * "sent" state is the only record of the click until the page is reloaded.
 */
import { useState } from 'react';
import { AlertCircle, Loader2, Send } from 'lucide-react';

import { businessChatApi } from './businessApi';

export default function BusinessLeadPrompt({ summary, packages }) {
    const [status, setStatus] = useState('idle'); // idle | sending | sent | dismissed | error

    if (!summary || status === 'dismissed') return null;

    const handleConfirm = async () => {
        setStatus('sending');
        try {
            await businessChatApi.createLead(summary, (packages || []).map((p) => p.id));
            setStatus('sent');
        } catch {
            setStatus('error');
        }
    };

    if (status === 'sent') {
        return (
            <section className="mt-6 pt-5 border-t border-[var(--p-line)]">
                <p className="text-[0.8125rem] text-[var(--p-ink-soft)]">
                    Đã gửi yêu cầu tới đội Micco. Chúng tôi sẽ liên hệ bạn sớm nhất.
                </p>
            </section>
        );
    }

    return (
        <section className="mt-6 pt-5 border-t border-[var(--p-line)]">
            <p className="p-eyebrow mb-2">Chuyển yêu cầu cho đội kinh doanh</p>
            <p className="text-[0.8125rem] leading-relaxed text-[var(--p-ink-soft)] mb-2">
                {summary}
            </p>
            {packages && packages.length > 0 && (
                <ul className="mb-3 space-y-1">
                    {packages.map((pkg) => (
                        <li key={pkg.id} className="text-[0.8125rem] text-[var(--p-ink-soft)]">
                            · {pkg.name}
                        </li>
                    ))}
                </ul>
            )}

            <div className="flex items-center gap-2">
                <button
                    type="button"
                    onClick={handleConfirm}
                    disabled={status === 'sending'}
                    className="p-btn !px-3 !py-2 !text-[0.8125rem]"
                >
                    {status === 'sending'
                        ? <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
                        : <Send className="w-3.5 h-3.5" aria-hidden="true" />}
                    Gửi yêu cầu tới đội Micco
                </button>
                <button
                    type="button"
                    onClick={() => setStatus('dismissed')}
                    disabled={status === 'sending'}
                    className="p-btn-ghost !px-3 !py-2 !text-[0.8125rem]"
                >
                    Bỏ qua
                </button>
            </div>

            {status === 'error' && (
                <p role="alert" className="mt-2 flex items-center gap-1.5 text-xs text-[var(--p-danger)]">
                    <AlertCircle className="w-3.5 h-3.5 shrink-0" aria-hidden="true" />
                    Không gửi được, vui lòng thử lại.
                </p>
            )}
        </section>
    );
}
