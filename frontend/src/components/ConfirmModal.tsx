import { createPortal } from "react-dom";

type Props = {
  mount: HTMLElement | null;
  open: boolean;
  title: string;
  message: string;
  confirmLabel: string;
  cancelLabel: string;
  /** Red-styled destructive confirm */
  danger?: boolean;
  /** Optional second action (e.g. merge vs replace) */
  secondaryLabel?: string;
  onSecondary?: () => void;
  onConfirm: () => void;
  onCancel: () => void;
};

export function ConfirmModal({
  mount,
  open,
  title,
  message,
  confirmLabel,
  cancelLabel,
  danger = false,
  secondaryLabel,
  onSecondary,
  onConfirm,
  onCancel,
}: Props) {
  if (!open || !mount) return null;

  const panelClass = danger
    ? "max-w-md rounded-2xl border border-red-400/25 bg-[#120808] p-5 shadow-[0_24px_80px_rgba(0,0,0,0.55)]"
    : "max-w-md rounded-2xl border border-outline-variant/30 bg-surface-container-high p-5 shadow-[0_24px_80px_rgba(0,0,0,0.55)]";
  const titleClass = danger
    ? "font-label text-sm font-bold uppercase tracking-wider text-red-200"
    : "font-label text-sm font-bold uppercase tracking-wider text-on-surface";
  const bodyClass = danger
    ? "mt-3 font-body text-sm leading-relaxed text-red-100/85"
    : "mt-3 font-body text-sm leading-relaxed text-on-surface-variant";
  const confirmBtnClass = danger
    ? "rounded-xl border border-red-400/50 bg-red-950/60 px-4 py-2 text-xs font-semibold text-red-100 hover:bg-red-900/50"
    : "rounded-xl border border-secondary/50 bg-secondary/15 px-4 py-2 text-xs font-semibold text-secondary hover:bg-secondary/25";

  return createPortal(
    <div
      className="fixed inset-0 z-[65000] flex items-center justify-center bg-black/55 px-4 backdrop-blur-[2px]"
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-modal-title"
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div className={panelClass} onClick={(e) => e.stopPropagation()}>
        <h2 id="confirm-modal-title" className={titleClass}>
          {title}
        </h2>
        <p className={bodyClass}>{message}</p>
        <div className="mt-5 flex flex-wrap justify-end gap-2">
          <button
            type="button"
            className="rounded-xl border border-outline-variant/35 px-4 py-2 text-xs font-semibold text-on-surface-variant hover:bg-white/5"
            onClick={onCancel}
          >
            {cancelLabel}
          </button>
          {secondaryLabel && onSecondary ? (
            <button
              type="button"
              className="rounded-xl border border-outline-variant/35 px-4 py-2 text-xs font-semibold text-on-surface hover:bg-surface-container-low"
              onClick={onSecondary}
            >
              {secondaryLabel}
            </button>
          ) : null}
          <button type="button" className={confirmBtnClass} onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>,
    mount,
  );
}
