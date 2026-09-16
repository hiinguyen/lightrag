/**
 * One turn in the portal conversation.
 *
 * Not the internal ChatMessage component: that one renders citation chips
 * wired to a document viewer, a knowledge-graph entity list and image
 * references, none of which a customer may reach. A source here is a label and
 * a page number, and it is not a link.
 */
import { AlertCircle, Building2 } from 'lucide-react';

import BusinessLeadPrompt from './BusinessLeadPrompt';
import BusinessPackageCards from './BusinessPackageCards';
import { renderMarkdown } from '../utils/markdown';

function SourceList({ sources }) {
    if (!sources || sources.length === 0) return null;

    return (
        <div className="mt-5 pt-4 border-t border-[var(--p-line)]">
            <p className="p-eyebrow mb-2.5">Nguồn</p>
            <ul className="space-y-1.5">
                {sources.map((source, index) => (
                    <li key={`${source.label}-${source.page_no}-${index}`} className="p-source">
                        <span className="p-source-index">{String(index + 1).padStart(2, '0')}</span>
                        <span>
                            {source.label}
                            {source.page_no > 0 && (
                                <span className="text-[var(--p-muted)]"> · tr.{source.page_no}</span>
                            )}
                        </span>
                    </li>
                ))}
            </ul>
        </div>
    );
}

export default function BusinessMessage({ message, isStreaming = false }) {
    if (message.role === 'user') {
        return (
            <article className="flex justify-end">
                <div className="p-turn-user max-w-[85%] sm:max-w-[75%]">
                    <p className="text-[0.9375rem] leading-relaxed text-[var(--p-ink)] whitespace-pre-wrap break-words">
                        {message.content}
                    </p>
                </div>
            </article>
        );
    }

    return (
        <article className="p-turn-assistant">
            <p className="p-eyebrow mb-3 flex items-center gap-2">
                <Building2 className="w-3 h-3" aria-hidden="true" />
                Trợ lý Micco
            </p>

            {message.status && !message.content && (
                <div className="mb-4" aria-live="polite">
                    <p className="p-eyebrow mb-2">
                        {message.status}
                    </p>
                    <div className="p-progress" role="presentation" />
                </div>
            )}

            {message.content && (
                <div
                    // aria-live so a screen reader follows the answer as it
                    // streams instead of only on completion.
                    aria-live={isStreaming ? 'polite' : 'off'}
                    dangerouslySetInnerHTML={{ __html: renderMarkdown(message.content) }}
                />
            )}

            {isStreaming && message.content && (
                <span
                    className="inline-block w-[2px] h-4 ml-0.5 align-text-bottom bg-[var(--p-accent)] animate-pulse"
                    aria-hidden="true"
                />
            )}

            {!isStreaming && <SourceList sources={message.sources} />}

            {!isStreaming && <BusinessPackageCards packages={message.recommendations} />}

            {!isStreaming && message.leadPrompt && (
                <BusinessLeadPrompt
                    summary={message.leadPrompt.summary}
                    packages={message.leadPrompt.packages}
                />
            )}

            {message.error && (
                <p role="alert" className="mt-4 flex items-start gap-2 text-sm text-[var(--p-danger)]">
                    <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" aria-hidden="true" />
                    {message.error}
                </p>
            )}
        </article>
    );
}
