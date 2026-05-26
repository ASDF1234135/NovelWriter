import { useState } from "react";
import { createPortal } from "react-dom";
import { useI18n } from "../../i18n/useI18n";

type Props = {
  /** When false, hide the trigger (e.g. read-only preview without edit handlers). */
  showTrigger?: boolean;
  className?: string;
};

function HelpSection({ title, items }: { title: string; items: string[] }) {
  return (
    <section className="rounded-xl border border-outline-variant/20 bg-surface-container/60 p-4">
      <h4 className="font-headline text-sm font-bold tracking-tight text-on-surface">{title}</h4>
      <ul className="mt-3 space-y-2 font-body text-sm leading-relaxed text-on-surface-variant">
        {items.map((item) => (
          <li key={item} className="flex gap-2">
            <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-secondary" aria-hidden />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** “?” trigger — opens a modal explaining DAG view/edit mode, nodes, and edges. */
export function DagEditHelpDialog({ showTrigger = true, className = "" }: Props) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const dialogMount = typeof document !== "undefined" ? document.body : null;

  if (!showTrigger) return null;

  const modeItems = [
    t("app.dag.help.modeLi1"),
    t("app.dag.help.modeLi2"),
    t("app.dag.help.modeLi3"),
    t("app.dag.help.modeLi4"),
  ];
  const nodeItems = [
    t("app.dag.help.nodesLi1"),
    t("app.dag.help.nodesLi2"),
    t("app.dag.help.nodesLi3"),
    t("app.dag.help.nodesLi4"),
    t("app.dag.help.nodesLi5"),
  ];
  const edgeItems = [
    t("app.dag.help.edgesLi1"),
    t("app.dag.help.edgesLi2"),
    t("app.dag.help.edgesLi3"),
    t("app.dag.help.edgesLi4"),
  ];

  return (
    <>
      <button
        type="button"
        className={
          className ||
          "flex h-10 w-10 items-center justify-center rounded-xl border border-amber-400/25 text-amber-100/90 transition hover:border-amber-400/45 hover:bg-amber-400/12 hover:text-amber-50"
        }
        onClick={() => setOpen(true)}
        aria-label={t("app.dag.help.triggerAria")}
        title={t("app.dag.help.triggerAria")}
      >
        <span className="material-symbols-outlined text-[22px] leading-none" aria-hidden>
          help
        </span>
      </button>

      {dialogMount && open
        ? createPortal(
            <div
              className="fixed inset-0 z-[66000] flex items-center justify-center bg-black/60 px-4 py-8 backdrop-blur-[2px]"
              role="dialog"
              aria-modal="true"
              aria-labelledby="dag-edit-help-title"
              onClick={(e) => {
                if (e.target === e.currentTarget) setOpen(false);
              }}
            >
              <div
                className="nb-panel flex max-h-[min(720px,90vh)] w-full max-w-lg flex-col overflow-hidden rounded-2xl border border-outline-variant/20 bg-surface-container-high shadow-[0_24px_80px_rgba(0,0,0,0.55)]"
                onClick={(e) => e.stopPropagation()}
              >
                <header className="flex items-start justify-between gap-3 border-b border-outline-variant/10 px-5 py-4">
                  <div>
                    <p className="font-label text-[10px] font-bold uppercase tracking-[0.28em] text-secondary/80">
                      {t("app.dag.help.kicker")}
                    </p>
                    <h2 id="dag-edit-help-title" className="mt-1 font-headline text-xl font-bold text-on-surface">
                      {t("app.dag.help.title")}
                    </h2>
                  </div>
                  <button
                    type="button"
                    className="rounded-xl border border-outline-variant/30 bg-surface-container px-3 py-2 text-xs font-semibold text-on-surface-variant hover:bg-surface-container-high"
                    onClick={() => setOpen(false)}
                  >
                    {t("common.close")}
                  </button>
                </header>
                <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-4">
                  <HelpSection title={t("app.dag.help.sectionMode")} items={modeItems} />
                  <HelpSection title={t("app.dag.help.sectionNodes")} items={nodeItems} />
                  <HelpSection title={t("app.dag.help.sectionEdges")} items={edgeItems} />
                </div>
              </div>
            </div>,
            dialogMount,
          )
        : null}
    </>
  );
}
