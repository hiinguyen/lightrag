/**
 * BusinessChatPage — the whole portal experience.
 *
 * Not ChatAssistant.jsx: that page is 1200+ lines and exposes a workspace
 * picker, a system-prompt editor, a knowledge-graph panel and a document
 * preview — every one of which is internal. Here there is nothing to
 * configure, because the server decides what the answer may be grounded in.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { AlertCircle, ArrowUp, Loader2, Trash2 } from 'lucide-react';

import BusinessMessage from './BusinessMessage';
import { businessChatApi, streamBusinessChat } from './businessApi';
import { useBusinessAuth } from './businessAuthContext';

// Static for now. Phase 6 replaces these with a business-specific endpoint —
// workspacesApi.getSuggestedQuestions is internal and takes a workspace id.
const SUGGESTIONS = [
    'Micco cung cấp những loại vật liệu nổ công nghiệp nào?',
    'Chúng tôi khai thác đá xây dựng, nên chọn giải pháp nào?',
    'Điều kiện và thủ tục để ký hợp đồng cung cấp là gì?',
];

let localId = 0;
const nextId = () => `local-${++localId}`;

export default function BusinessChatPage() {
    const { user } = useBusinessAuth();
    const [messages, setMessages] = useState([]);
    const [draft, setDraft] = useState('');
    const [sending, setSending] = useState(false);
    const [loadError, setLoadError] = useState('');
    const [loadingHistory, setLoadingHistory] = useState(true);

    const endRef = useRef(null);
    const inputRef = useRef(null);

    // Load the server-side conversation. History lives in the database, so a
    // customer picks up where they left off on any device.
    useEffect(() => {
        let cancelled = false;

        businessChatApi
            .history()
            .then((data) => {
                if (cancelled) return;
                setMessages(
                    (data?.messages || []).map((m) => ({
                        id: m.message_id || nextId(),
                        role: m.role,
                        content: m.content,
                        sources: m.sources || [],
                        recommendations: m.recommendations || [],
                        leadPrompt: null,
                    })),
                );
            })
            .catch((error) => {
                if (!cancelled) setLoadError(error.message);
            })
            .finally(() => {
                if (!cancelled) setLoadingHistory(false);
            });

        return () => { cancelled = true; };
    }, []);

    useEffect(() => {
        endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }, [messages]);

    // Collapse the composer again after a send clears the draft.
    useEffect(() => {
        if (draft === '' && inputRef.current) {
            inputRef.current.style.height = 'auto';
        }
    }, [draft]);

    const updateLast = useCallback((patch) => {
        setMessages((current) => {
            if (current.length === 0) return current;
            const last = current[current.length - 1];
            return [...current.slice(0, -1), { ...last, ...patch(last) }];
        });
    }, []);

    const send = useCallback(async (text) => {
        const question = text.trim();
        if (!question || sending) return;

        setDraft('');
        setSending(true);
        setMessages((current) => [
            ...current,
            { id: nextId(), role: 'user', content: question, sources: [], recommendations: [] },
            {
                id: nextId(),
                role: 'assistant',
                content: '',
                sources: [],
                recommendations: [],
                leadPrompt: null,
                status: 'Đang gửi câu hỏi',
            },
        ]);

        await streamBusinessChat(question, {
            onStatus: (detail) => updateLast(() => ({ status: detail })),
            onSources: (sources) => updateLast(() => ({ sources })),
            onDelta: (chunk) => updateLast((last) => ({
                content: last.content + chunk,
                status: '',
            })),
            onRecommendations: (packages) => updateLast(() => ({ recommendations: packages })),
            onLeadPrompt: (payload) => updateLast(() => ({ leadPrompt: payload })),
            onComplete: (payload) => updateLast(() => ({
                content: payload.answer,
                sources: payload.sources || [],
                recommendations: payload.recommendations || [],
                status: '',
            })),
            onError: (error) => updateLast(() => ({ status: '', error: error.message })),
        });

        setSending(false);
        inputRef.current?.focus();
    }, [sending, updateLast]);

    const handleClear = useCallback(async () => {
        try {
            await businessChatApi.clearHistory();
            setMessages([]);
        } catch (error) {
            setLoadError(error.message);
        }
    }, []);

    const handleKeyDown = (event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            send(draft);
        }
    };

    // Grow with the text instead of clipping it. A single row is too short for
    // a wrapped question at 320px, and max-h-40 caps the growth.
    const handleInput = (event) => {
        const field = event.target;
        field.style.height = 'auto';
        field.style.height = `${field.scrollHeight}px`;
    };

    const isEmpty = messages.length === 0;

    return (
        <div className="flex-1 flex flex-col min-h-0">
            <div className="flex-1 overflow-y-auto">
                <div className="mx-auto w-full max-w-[var(--p-measure)] px-4 sm:px-6 py-10 sm:py-14">
                    {loadingHistory ? (
                        <div className="flex items-center gap-3 text-sm text-[var(--p-muted)]">
                            <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
                            Đang tải hội thoại...
                        </div>
                    ) : isEmpty ? (
                        <section>
                            <p className="p-eyebrow mb-4">
                                {user?.company_name ? `Xin chào, ${user.company_name}` : 'Xin chào'}
                            </p>
                            <h1 className="p-display text-3xl sm:text-4xl leading-[1.15] text-[var(--p-ink)] mb-4">
                                Bạn muốn tìm hiểu điều gì về Micco?
                            </h1>
                            <p className="text-[0.9375rem] leading-relaxed text-[var(--p-ink-soft)] mb-10 max-w-lg">
                                Đặt câu hỏi về sản phẩm, dịch vụ hoặc điều khoản hợp đồng. Nếu nhu cầu
                                của bạn còn rộng, hãy mô tả công việc — trợ lý sẽ hỏi thêm để tư vấn
                                đúng hướng.
                            </p>

                            <p className="p-eyebrow mb-3">Gợi ý</p>
                            <ul className="space-y-2">
                                {SUGGESTIONS.map((suggestion) => (
                                    <li key={suggestion}>
                                        <button
                                            type="button"
                                            className="p-suggestion"
                                            onClick={() => send(suggestion)}
                                        >
                                            {suggestion}
                                        </button>
                                    </li>
                                ))}
                            </ul>
                        </section>
                    ) : (
                        <div role="log" className="space-y-10">
                            {messages.map((message, index) => (
                                <BusinessMessage
                                    key={message.id}
                                    message={message}
                                    isStreaming={sending && index === messages.length - 1}
                                />
                            ))}
                        </div>
                    )}

                    {loadError && (
                        <p role="alert" className="mt-8 flex items-start gap-2 text-sm text-[var(--p-danger)]">
                            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" aria-hidden="true" />
                            {loadError}
                        </p>
                    )}

                    <div ref={endRef} />
                </div>
            </div>

            {/* Composer. A hairline rule on the paper ground rather than a
                floating card, so it reads as part of the page. */}
            <div className="border-t border-[var(--p-line)] bg-[var(--p-bg)]">
                <div className="mx-auto w-full max-w-[var(--p-measure)] px-4 sm:px-6 py-4">
                    <form
                        onSubmit={(event) => { event.preventDefault(); send(draft); }}
                        className="flex items-end gap-2"
                    >
                        <label htmlFor="business-question" className="sr-only">
                            Câu hỏi của bạn
                        </label>
                        <textarea
                            id="business-question"
                            ref={inputRef}
                            rows={1}
                            value={draft}
                            onChange={(event) => setDraft(event.target.value)}
                            onInput={handleInput}
                            onKeyDown={handleKeyDown}
                            placeholder="Đặt câu hỏi cho Micco..."
                            maxLength={2000}
                            className="p-field resize-none max-h-40 overflow-y-auto leading-relaxed"
                        />
                        <button
                            type="submit"
                            disabled={sending || !draft.trim()}
                            className="p-btn !px-3.5 !py-3 shrink-0"
                            aria-label="Gửi câu hỏi"
                        >
                            {sending
                                ? <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
                                : <ArrowUp className="w-4 h-4" aria-hidden="true" />}
                        </button>
                    </form>

                    <div className="mt-2.5 flex items-center justify-end sm:justify-between gap-3">
                        <p className="hidden sm:block text-[0.6875rem] text-[var(--p-muted)]">
                            Enter để gửi · Shift + Enter để xuống dòng
                        </p>
                        {!isEmpty && (
                            <button
                                type="button"
                                onClick={handleClear}
                                disabled={sending}
                                className="p-btn-ghost !px-2 !py-1 !text-[0.6875rem]"
                            >
                                <Trash2 className="w-3 h-3" aria-hidden="true" />
                                Xoá hội thoại
                            </button>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}
