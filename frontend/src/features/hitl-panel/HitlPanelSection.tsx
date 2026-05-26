import type { ReactNode } from "react";

type Props = {
  sectionId: string;
  title: string;
  children: ReactNode;
  /** Visual accent: reason uses warm highlight; others neutral. */
  variant?: "reason" | "default";
  className?: string;
};

export function HitlPanelSection({ sectionId, title, children, variant = "default", className = "" }: Props) {
  const accent =
    variant === "reason"
      ? "border-tertiary/25 bg-tertiary/[0.06]"
      : "border-outline-variant/15 bg-surface-container-highest/25";
  const header =
    variant === "reason"
      ? "border-tertiary/15 bg-tertiary/[0.08]"
      : "border-outline-variant/10 bg-surface-container-highest/40";

  return (
    <section
      id={sectionId}
      aria-labelledby={`${sectionId}-title`}
      className={`hitl-panel-section mb-3 overflow-hidden rounded-xl border ${accent} ${className}`}
    >
      <header className={`border-b px-3 py-2 ${header}`}>
        <h3 id={`${sectionId}-title`} className="font-headline text-[11px] font-bold uppercase tracking-[0.2em] text-tertiary">
          {title}
        </h3>
      </header>
      <div className="px-3 py-3">{children}</div>
    </section>
  );
}
