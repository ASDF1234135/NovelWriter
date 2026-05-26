import { useMemo, useState, type Dispatch, type SetStateAction } from "react";
import type { GraphSnapshot, WorkflowPayload } from "../../types";
import { isDevToolsEnabled } from "../../dev/devTools";
import { buildHitlDevPayload, HITL_DEV_SCENARIOS, type HitlDevPayload } from "../../dev/hitlDevMocks";
import { HITL_REASON, type HitlReasonValue } from "./hitlCopy";
import { useI18n } from "../../i18n/useI18n";

export type HitlDevPanelProps = {
  workflow: WorkflowPayload | null;
  setWorkflow: Dispatch<SetStateAction<WorkflowPayload | null>>;
  setGraph?: Dispatch<SetStateAction<GraphSnapshot | null>>;
  /** Called when injecting Chapter_Draft_Review (needs review view + ChapterReviewGate). */
  onNavigateReview?: () => void;
  variant?: "default" | "compact";
};

function activeReason(workflow: WorkflowPayload | null): string {
  if (!workflow) return "";
  const waiting =
    workflow.run.requires_hitl === true ||
    workflow.run.status === "WAITING_HITL" ||
    workflow.state.workflow_status === "WAITING_HITL";
  if (!waiting) return "";
  return String(workflow.run.hitl_reason ?? workflow.state.hitl_reason ?? "").trim();
}

export function HitlDevPanel({
  workflow,
  setWorkflow,
  setGraph,
  onNavigateReview,
  variant = "default",
}: HitlDevPanelProps) {
  const { t } = useI18n();
  const [lastInjected, setLastInjected] = useState<HitlReasonValue | "">("");

  const scenarios = useMemo(() => HITL_DEV_SCENARIOS, []);
  const currentReason = activeReason(workflow);
  const compact = variant === "compact";

  if (!isDevToolsEnabled()) return null;

  const shell = compact
    ? "glass-panel rounded-xl border border-warning/35 bg-warning/[0.08] p-3 shadow-glow"
    : "rounded-xl border border-warning/35 bg-warning/[0.08] p-4 shadow-glow";

  function applyPayload(payload: HitlDevPayload, reason: HitlReasonValue) {
    setWorkflow(payload.workflow);
    if (payload.graph && setGraph) setGraph(payload.graph);
    setLastInjected(reason);
    if (reason === HITL_REASON.CHAPTER_DRAFT_REVIEW) onNavigateReview?.();
  }

  function resetHitl() {
    if (!workflow) return;
    setWorkflow({
      ...workflow,
      run: {
        ...workflow.run,
        status: "RUNNING",
        requires_hitl: false,
        hitl_reason: "",
        hitl_decision_mode: "NONE",
        hitl_context: null,
      },
      state: {
        ...(workflow.state ?? {}),
        workflow_status: "RUNNING",
        requires_hitl: false,
        hitl_reason: "",
        pending_hitl_options: [],
      },
    });
    setLastInjected("");
  }

  const selectedMeta = scenarios.find((s) => s.reason === lastInjected);

  return (
    <section className={shell} aria-label={t("hitl.dev.aria")} data-testid="hitl-dev-panel">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-label text-[10px] font-bold uppercase tracking-[0.2em] text-warning">
            {t("hitl.dev.badge")}
          </div>
          <p className="mt-0.5 font-body text-xs leading-relaxed text-on-surface-variant">
            {t("hitl.dev.subtitle")}
          </p>
        </div>
        <button
          type="button"
          className="btn-secondary shrink-0 text-[11px]"
          onClick={resetHitl}
          disabled={!workflow || !currentReason}
          title={!workflow ? t("hitl.dev.resetNoWorkflow") : undefined}
        >
          {t("hitl.dev.reset")}
        </button>
      </div>

      <label className="mt-3 flex min-w-0 flex-col gap-1.5 font-body text-xs text-on-surface">
        <span className="font-label text-[10px] uppercase tracking-wider text-outline">
          {t("hitl.dev.reasonLabel")}
        </span>
        <select
          className="auteur-input h-9 w-full text-xs"
          value=""
          onChange={(e) => {
            const v = e.target.value as HitlReasonValue;
            if (!v) return;
            applyPayload(buildHitlDevPayload(v, workflow), v);
          }}
          data-testid="hitl-dev-reason-select"
        >
          <option value="">{t("hitl.dev.selectPlaceholder")}</option>
          {scenarios.map((row) => (
            <option key={row.reason} value={row.reason}>
              {row.title} · {row.reason}
            </option>
          ))}
        </select>
      </label>

      {currentReason ? (
        <div className="mt-2 rounded-lg border border-outline-variant/20 bg-surface-container-highest/40 px-2.5 py-2">
          <p className="font-mono text-[10px] text-on-surface-variant">
            <span className="text-warning">{t("hitl.dev.active")}</span> {currentReason}
          </p>
          {selectedMeta && selectedMeta.reason === currentReason ? (
            <ul className="mt-1.5 space-y-0.5 font-body text-[10px] text-on-surface-variant">
              {selectedMeta.optionIds.length > 0 ? (
                <li>
                  {t("hitl.dev.options")}: {selectedMeta.optionIds.join(", ")}
                </li>
              ) : (
                <li>{t("hitl.dev.optionsFormOnly")}</li>
              )}
              {selectedMeta.solutionIds.length > 0 ? (
                <li>
                  {t("hitl.dev.solutions")}: {selectedMeta.solutionIds.join(", ")}
                </li>
              ) : null}
            </ul>
          ) : null}
        </div>
      ) : (
        <p className="mt-2 font-body text-[10px] text-on-surface-variant">{t("hitl.dev.idleHint")}</p>
      )}

      {lastInjected === HITL_REASON.CHAPTER_DRAFT_REVIEW ? (
        <p className="mt-2 rounded-md border border-tertiary/30 bg-tertiary/10 px-2 py-1.5 font-body text-[10px] text-tertiary">
          {t("hitl.dev.chapterReviewHint")}
        </p>
      ) : null}
    </section>
  );
}
