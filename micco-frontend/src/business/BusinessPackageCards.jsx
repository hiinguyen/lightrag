/**
 * Suggested package cards under an assistant turn.
 *
 * Shown when the model judged the customer's need still broad. Every field
 * here comes from the server's card projection (business_packages.to_card), so
 * this component renders what it is given and derives nothing.
 *
 * Deliberately not clickable: a card that looks pressable but does nothing
 * is worse than a plain one. Acting on a suggestion happens through the
 * chat's [[LEAD:...]] flow (see BusinessLeadPrompt), not by clicking a card.
 */
import { Package } from 'lucide-react';

export default function BusinessPackageCards({ packages }) {
    if (!packages || packages.length === 0) return null;

    return (
        <section className="mt-6 pt-5 border-t border-[var(--p-line)]">
            <p className="p-eyebrow mb-3">Gói có thể phù hợp</p>

            <ul className="space-y-3">
                {packages.map((pkg) => (
                    <li key={pkg.id} className="p-package">
                        <div className="flex items-baseline gap-2 mb-1.5">
                            <Package
                                className="w-3.5 h-3.5 shrink-0 translate-y-0.5 text-[var(--p-accent)]"
                                aria-hidden="true"
                            />
                            <h3 className="p-display text-[0.9375rem] text-[var(--p-ink)] leading-snug">
                                {pkg.name}
                            </h3>
                        </div>

                        <p className="p-eyebrow !text-[0.625rem] mb-2">{pkg.category}</p>

                        <p className="text-[0.8125rem] leading-relaxed text-[var(--p-ink-soft)]">
                            {pkg.summary}
                        </p>

                        {pkg.highlights?.length > 0 && (
                            <ul className="mt-2.5 space-y-1">
                                {pkg.highlights.map((highlight, index) => (
                                    <li
                                        key={`${pkg.id}-h${index}`}
                                        className="flex gap-2 text-[0.8125rem] text-[var(--p-ink-soft)]"
                                    >
                                        <span aria-hidden="true" className="text-[var(--p-accent)]">·</span>
                                        <span>{highlight}</span>
                                    </li>
                                ))}
                            </ul>
                        )}

                        {pkg.price_note && (
                            <p className="mt-2.5 text-xs text-[var(--p-muted)]">{pkg.price_note}</p>
                        )}
                    </li>
                ))}
            </ul>
        </section>
    );
}
