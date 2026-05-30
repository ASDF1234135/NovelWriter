import { Suspense, lazy, useCallback, useMemo, useState } from "react";
import { ConfirmModal } from "../../components/ConfirmModal";
import { useI18n } from "../../i18n/useI18n";
import { useUnsavedChangesGuard } from "./useUnsavedChangesGuard";

const ChapterReviewEditor = lazy(() => import("./ChapterReviewEditor"));

export type ChapterReviewGateProps = {
  /**
   * `"app"` — default dark-surface tokens (legacy).
   * `"manuscript"` — warm ink-on-cream palette for the atelier review reader.
   */
  surface?: "app" | "manuscript";
  /** The draft body produced by reader. */
  draft: string;
  /** Last reader literary score (0-100). */
  readerScore?: number | null;
  /** Disable all controls while an API call is in flight. */
  busy: boolean;
  /**
   * Approve handler.
   *   - When the user did not edit the draft: `edited === false`, `content`
   *     equals `draft`, so the caller should route to `sendHitlDecision("APPROVE_DRAFT")`.
   *   - When the user edited: `edited === true`, send `sendDraftEdit({chapter_content, resume_from:"chunker"})`.
   */
  onApprove: (content: string, edited: boolean) => Promise<void>;
  onAbandon: () => Promise<void>;
  onRerun: () => Promise<void>;
};

type PendingAction = null | "rerun" | "abandon" | "unsavedRoute";

export function ChapterReviewGate({
  surface = "app",
  draft,
  readerScore,
  busy,
  onApprove,
  onAbandon,
  onRerun,
}: ChapterReviewGateProps) {
  const { t } = useI18n();
  const onPaper = surface === "manuscript";
  const initialDraft = useMemo(() => String(draft ?? ""), [draft]);
  const [content, setContent] = useState<string>(initialDraft);
  const [edited, setEdited] = useState<boolean>(false);
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [pending, setPending] = useState<PendingAction>(null);

  const guardActive = edited && !submitting;
  const blocker = useUnsavedChangesGuard(guardActive, t("chapterReview.unsavedWarning"));

  const disabled = busy || submitting;

  const handleEditorChange = useCallback(
    (next: string) => {
      setContent(next);
      setEdited(next.trim() !== initialDraft.trim());
    },
    [initialDraft],
  );

  async function handleApproveClick() {
    if (disabled) return;
    setSubmitting(true);
    try {
      await onApprove(content, edited);
    } finally {
      setSubmitting(false);
    }
  }

  function requestRerun() {
    if (disabled) return;
    setPending("rerun");
  }

  function requestAbandon() {
    if (disabled) return;
    setPending("abandon");
  }

  async function confirmPending() {
    const action = pending;
    setPending(null);
    if (!action || disabled) return;
    setSubmitting(true);
    try {
      if (action === "rerun") {
        await onRerun();
      } else if (action === "abandon") {
        await onAbandon();
      }
    } finally {
      setSubmitting(false);
    }
  }

  function dismissPending() {
    setPending(null);
  }

  const mount = typeof document !== "undefined" ? document.body : null;
  const confirmTitle = pending === "abandon" ? t("chapterReview.abandon") : t("chapterReview.rerun");
  const confirmMessage =
    pending === "abandon"
      ? t("chapterReview.abandonConfirm")
      : pending === "unsavedRoute"
        ? t("chapterReview.unsavedBody")
        : t("chapterReview.rerunConfirm");

  return (
    <div
      className={onPaper ? "chapter-review-gate flex flex-col gap-6" : "flex flex-col gap-5"}
      data-testid="chapter-review-gate"
      data-surface={surface}
    >
      <div
        role="note"
        className={
          onPaper
            ? "rounded-2xl border border-[rgba(122,90,40,0.28)] bg-gradient-to-br from-[#fff9ed] to-[#f5e8d0] px-5 py-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.65),0_8px_28px_-12px_rgba(60,40,10,0.25)]"
            : "rounded-xl border border-tertiary/30 bg-tertiary/10 px-4 py-3 font-body text-sm leading-relaxed text-on-surface"
        }
      >
        <div
          className={
            onPaper
              ? "flex items-center gap-2 border-b border-[rgba(122,90,40,0.12)] pb-3 font-label text-[11px] font-bold uppercase tracking-[0.22em] text-[#6b4f1f]"
              : "flex items-center gap-2 font-label text-[11px] font-bold uppercase tracking-wider text-tertiary"
          }
        >
          <span className="material-symbols-outlined text-base" aria-hidden>
            {onPaper ? "rate_review" : "edit_note"}
          </span>
          <span>{t("chapterReview.title")}</span>
          {typeof readerScore === "number" ? (
            <span
              className={
                onPaper
                  ? "ml-auto rounded-full border border-[rgba(122,90,40,0.35)] bg-white/70 px-2.5 py-0.5 font-mono text-[11px] text-[#4a3a18]"
                  : "ml-auto rounded-full border border-tertiary/30 bg-surface-container-highest/70 px-2 py-0.5 font-mono text-[11px] text-on-surface-variant"
              }
            >
              {t("chapterReview.readerScore", undefined, { score: readerScore })}
            </span>
          ) : null}
        </div>
        <p className={onPaper ? "mt-3 font-body text-sm leading-relaxed text-[#3d2f1f]" : "mt-2"}>
          {t("chapterReview.draftNotice")}
        </p>
        <p className={onPaper ? "mt-2 font-body text-sm leading-relaxed text-[#5c4a32]/90" : "mt-1 text-on-surface-variant"}>
          {t("chapterReview.abandonHint")}
        </p>
        <p className={onPaper ? "mt-1.5 font-body text-xs leading-relaxed text-[#5c4a32]/85" : "mt-1 text-xs text-on-surface-variant"}>
          {t("chapterReview.aiReminder")}
        </p>
      </div>

      <div
        className={
          onPaper
            ? "rounded-2xl border border-[rgba(90,70,45,0.14)] bg-[#fdf8ee]/95 p-1 shadow-[inset_0_0_0_1px_rgba(255,255,255,0.5)] sm:p-2"
            : "rounded-xl border border-outline-variant/15 bg-surface-container-low/60 p-4"
        }
      >
        <Suspense
          fallback={
            <div className="space-y-3 px-3 py-3" aria-live="polite">
              <p
                className={
                  onPaper
                    ? "font-label text-xs uppercase tracking-wider text-[#7a5a28]"
                    : "font-label text-xs uppercase tracking-wider text-outline"
                }
              >
                {t("chapterReview.editorLoading")}
              </p>
              <pre
                className={
                  onPaper
                    ? "whitespace-pre-wrap font-body text-lg leading-[1.85] text-[#2a221a]/88"
                    : "whitespace-pre-wrap font-body text-lg leading-[1.8] text-on-surface/90"
                }
              >
                {initialDraft}
              </pre>
            </div>
          }
        >
          <ChapterReviewEditor
            initialDoc={initialDraft}
            busy={disabled}
            manuscriptSurface={onPaper}
            onChange={handleEditorChange}
          />
        </Suspense>
      </div>

      <div
        className={
          onPaper
            ? "sticky bottom-2 z-10 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[rgba(90,70,45,0.18)] bg-[#fbf6e8]/95 px-4 py-3 shadow-[0_12px_40px_-16px_rgba(40,28,10,0.35)] backdrop-blur-sm"
            : "sticky bottom-2 z-10 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-outline-variant/15 bg-surface-container-high/95 px-4 py-3 shadow-glow backdrop-blur"
        }
      >
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={requestAbandon}
            disabled={disabled}
            className={
              onPaper
                ? "rounded-xl border border-[#b54a40]/45 bg-[#fff0ee] px-3 py-2 text-xs font-semibold text-[#8a2e26] hover:bg-[#ffe4e0] disabled:cursor-not-allowed disabled:opacity-50"
                : "rounded-xl border border-error/40 bg-error/10 px-3 py-2 text-xs font-semibold text-error hover:bg-error/20 disabled:cursor-not-allowed disabled:opacity-50"
            }
            data-testid="chapter-review-abandon"
          >
            {t("chapterReview.abandon")}
          </button>
          <button
            type="button"
            onClick={requestRerun}
            disabled={disabled}
            className={
              onPaper
                ? "rounded-xl border border-[rgba(90,70,45,0.35)] bg-white/80 px-3 py-2 text-xs font-semibold text-[#4a3a22] hover:bg-[#f5ead6] disabled:cursor-not-allowed disabled:opacity-50"
                : "rounded-xl border border-outline-variant/30 bg-surface-container-highest px-3 py-2 text-xs font-semibold text-on-surface hover:bg-surface-container-high disabled:cursor-not-allowed disabled:opacity-50"
            }
            data-testid="chapter-review-rerun"
          >
            {t("chapterReview.rerun")}
          </button>
        </div>
        <button
          type="button"
          onClick={handleApproveClick}
          disabled={disabled}
          className={
            onPaper
              ? "inline-flex items-center gap-2 rounded-full bg-gradient-to-br from-[#c9a227] via-[#a67c1a] to-[#7a5a12] px-5 py-2.5 text-sm font-bold text-[#1f1608] shadow-[0_4px_14px_-4px_rgba(90,60,10,0.55)] transition-[transform,filter] hover:brightness-105 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
              : "btn-primary-gradient flex items-center gap-2 px-5 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50"
          }
          data-testid="chapter-review-approve"
        >
          <span className="material-symbols-outlined text-base">check_circle</span>
          {edited ? t("chapterReview.approveEdited") : t("chapterReview.approve")}
        </button>
      </div>

      <ConfirmModal
        mount={mount}
        open={pending === "rerun" || pending === "abandon"}
        title={confirmTitle}
        message={confirmMessage}
        confirmLabel={pending === "abandon" ? t("chapterReview.abandon") : t("chapterReview.rerun")}
        cancelLabel={t("common.cancel")}
        danger={pending === "abandon"}
        onConfirm={() => void confirmPending()}
        onCancel={dismissPending}
      />

      <ConfirmModal
        mount={mount}
        open={blocker.state === "blocked"}
        title={t("chapterReview.unsavedTitle")}
        message={t("chapterReview.unsavedBody")}
        confirmLabel={t("chapterReview.unsavedLeave")}
        cancelLabel={t("chapterReview.unsavedStay")}
        danger
        onConfirm={() => blocker.state === "blocked" && blocker.proceed?.()}
        onCancel={() => blocker.state === "blocked" && blocker.reset?.()}
      />
    </div>
  );
}
