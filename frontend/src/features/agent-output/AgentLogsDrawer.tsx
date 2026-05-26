import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import type { WorkflowPayload } from "../../types";
import { useI18n } from "../../i18n/useI18n";
import { AgentOutputView } from "./AgentOutputView";

type Props = {
  open: boolean;
  onClose: () => void;
  workflow: WorkflowPayload | null;
};

/**
 * Bottom slide-up drawer that holds {@link AgentOutputView}. Replaces the
 * progress/logs tabs that used to live in the review side rail.
 *
 * Behavior:
 *  - Esc closes the drawer.
 *  - Backdrop click closes the drawer.
 *  - Focus is moved to the close button on open so keyboard users can Tab
 *    through the agent output without losing the drawer focus trap.
 *  - The drawer is rendered into `document.body` via a portal so it overlays
 *    the manuscript stage regardless of stacking context.
 */
export function AgentLogsDrawer({ open, onClose, workflow }: Props) {
  const { t } = useI18n();
  const closeBtnRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    closeBtnRef.current?.focus();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    }
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [open, onClose]);

  if (!open) return null;
  const mount = typeof document !== "undefined" ? document.body : null;
  if (!mount) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[80] flex items-end justify-center"
      role="dialog"
      aria-modal="true"
      aria-label={t("reviewShell.drawer.title")}
    >
      <button
        type="button"
        aria-hidden="true"
        tabIndex={-1}
        onClick={onClose}
        className="absolute inset-0 cursor-default bg-black/55 backdrop-blur-sm"
      />
      <section
        className="atelier-drawer-enter nb-panel relative max-h-[78vh] w-full max-w-5xl rounded-t-2xl shadow-glow"
        style={{
          boxShadow:
            "0 -24px 64px -16px rgba(0,0,0,0.7), 0 0 0 1px rgba(233,195,73,0.18)",
        }}
      >
        <header className="flex items-center justify-between border-b border-secondary/20 px-5 py-3">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-base text-secondary" aria-hidden>
              menu_book
            </span>
            <h2 className="font-headline text-sm font-bold uppercase tracking-[0.24em] text-secondary">
              {t("reviewShell.drawer.title")}
            </h2>
          </div>
          <button
            ref={closeBtnRef}
            type="button"
            onClick={onClose}
            className="btn-secondary text-[11px]"
            aria-label={t("reviewShell.drawer.close")}
            data-testid="agent-logs-drawer-close"
          >
            {t("reviewShell.drawer.close")}
          </button>
        </header>
        <div className="max-h-[calc(78vh-3.25rem)] overflow-auto p-5">
          <AgentOutputView workflow={workflow} variant="default" />
        </div>
      </section>
    </div>,
    mount,
  );
}
