import { Suspense, lazy, useCallback, useMemo, useState } from "react";
import { ConfirmModal } from "../../components/ConfirmModal";
import { useI18n } from "../../i18n/useI18n";
import { useUnsavedChangesGuard } from "./useUnsavedChangesGuard";

const ChapterReviewEditor = lazy(() => import("./ChapterReviewEditor"));

export type ChapterReviewGateProps = {
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
  draft,
  readerScore,
  busy,
  onApprove,
  onAbandon,
  onRerun,
}: ChapterReviewGateProps) {
  const { t } = useI18n();
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
    <div className="flex flex-col gap-5" data-testid="chapter-review-gate">
      <div
        role="note"
        className="rounded-xl border border-tertiary/30 bg-tertiary/10 px-4 py-3 font-body text-sm leading-relaxed text-on-surface"
      >
        <div className="flex items-center gap-2 font-label text-[11px] font-bold uppercase tracking-wider text-tertiary">
          <span className="material-symbols-outlined text-base">edit_note</span>
          <span>{t("chapterReview.title")}</span>
          {typeof readerScore === "number" ? (
            <span className="ml-auto rounded-full border border-tertiary/30 bg-surface-container-highest/70 px-2 py-0.5 font-mono text-[11px] text-on-surface-variant">
              {t("chapterReview.readerScore", undefined, { score: readerScore })}
            </span>
          ) : null}
        </div>
        <p className="mt-2">{t("chapterReview.draftNotice")}</p>
        <p className="mt-1 text-on-surface-variant">{t("chapterReview.abandonHint")}</p>
      </div>

      <div className="rounded-xl border border-outline-variant/15 bg-surface-container-low/60 p-4">
        <Suspense
          fallback={
            <div className="space-y-3" aria-live="polite">
              <p className="font-label text-xs uppercase tracking-wider text-outline">
                {t("chapterReview.editorLoading")}
              </p>
              <pre className="whitespace-pre-wrap font-body text-lg leading-[1.8] text-on-surface/90">
                {initialDraft}
              </pre>
            </div>
          }
        >
          <ChapterReviewEditor initialDoc={initialDraft} busy={disabled} onChange={handleEditorChange} />
        </Suspense>
      </div>

      <div className="sticky bottom-2 z-10 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-outline-variant/15 bg-surface-container-high/95 px-4 py-3 shadow-glow backdrop-blur">
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={requestAbandon}
            disabled={disabled}
            className="rounded-xl border border-error/40 bg-error/10 px-3 py-2 text-xs font-semibold text-error hover:bg-error/20 disabled:cursor-not-allowed disabled:opacity-50"
            data-testid="chapter-review-abandon"
          >
            {t("chapterReview.abandon")}
          </button>
          <button
            type="button"
            onClick={requestRerun}
            disabled={disabled}
            className="rounded-xl border border-outline-variant/30 bg-surface-container-highest px-3 py-2 text-xs font-semibold text-on-surface hover:bg-surface-container-high disabled:cursor-not-allowed disabled:opacity-50"
            data-testid="chapter-review-rerun"
          >
            {t("chapterReview.rerun")}
          </button>
        </div>
        <button
          type="button"
          onClick={handleApproveClick}
          disabled={disabled}
          className="btn-primary-gradient flex items-center gap-2 px-5 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-50"
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
