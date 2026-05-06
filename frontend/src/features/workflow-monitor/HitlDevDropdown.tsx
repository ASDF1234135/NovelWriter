import type { Dispatch, SetStateAction } from "react";
import type { WorkflowPayload } from "../../types";
import { HITL_REASON, HITL_REASON_MATRIX, type HitlReasonValue } from "../hitl-panel/hitlCopy";

type Props = {
  workflow: WorkflowPayload | null;
  setWorkflow: Dispatch<SetStateAction<WorkflowPayload | null>>;
  variant?: "default" | "compact";
};

type PendingOption = { id: string; label: string };

function shouldShowDevControls(): boolean {
  const flag = String(import.meta.env.VITE_ENABLE_DEV_TOOLS ?? "").trim();
  return flag === "1" || flag.toLowerCase() === "true";
}

function defaultResumeFrom(reason: string): string {
  if (reason === HITL_REASON.PLAN_LOOP) return "plan_supervisor";
  if (reason === HITL_REASON.DRAFT_LOOP) return "author";
  if (reason === HITL_REASON.EXTRACTION_GATE) return "extraction_gate";
  if (reason === HITL_REASON.B_STORY) return "anchor_resolve";
  if (reason === HITL_REASON.CONTEXT) return "graph_rag";
  if (reason === HITL_REASON.ALIGNMENT_RULES_REQUIRED) return "logic_alignment";
  if (reason === HITL_REASON.OUTPUT_LANGUAGE) return "output_language_gate";
  if (reason === HITL_REASON.B_STORY_COOLDOWN) return "director";
  if (reason === HITL_REASON.RESOLUTION_TACTIC) return "plan_supervisor";
  if (reason === HITL_REASON.ENDING_VIBE) return "plan_supervisor";
  return "author";
}

function optionIdsForReason(reason: string): string[] {
  const row = HITL_REASON_MATRIX.find((r) => r.reason === reason);
  if (!row) return [];
  return Array.isArray(row.optionIds) ? row.optionIds : [];
}

function buildMockOptions(reason: string): PendingOption[] {
  const ids = optionIdsForReason(reason);
  if (ids.length === 0) return [];
  return ids.map((id) => ({ id, label: id }));
}

function buildNextWorkflow(prev: WorkflowPayload | null, reason: HitlReasonValue): WorkflowPayload {
  const base: WorkflowPayload =
    prev ?? ({
      run: {
        run_id: "dev_mock_run",
        story_id: "dev_mock_story",
        chapter_id: 1,
        status: "IDLE",
        current_agent: "",
        requires_hitl: false,
        hitl_reason: "",
        hitl_decision_mode: "NONE",
        hitl_context: null,
      },
      state: {},
      steps: [],
    } satisfies WorkflowPayload);

  const pending = buildMockOptions(reason);
  const resumeFrom = defaultResumeFrom(reason);

  return {
    ...base,
    run: {
      ...base.run,
      status: "WAITING_HITL",
      requires_hitl: true,
      hitl_reason: reason,
      hitl_decision_mode: pending.length ? "CHOICE" : "NONE",
    },
    state: {
      ...(base.state ?? {}),
      workflow_status: "WAITING_HITL",
      requires_hitl: true,
      hitl_reason: reason,
      resume_from: resumeFrom,
      pending_hitl_options: pending,
    },
  };
}

export function HitlDevDropdown({ workflow, setWorkflow, variant = "default" }: Props) {
  if (!shouldShowDevControls()) return null;
  const compact = variant === "compact";
  const classShell = compact
    ? "glass-panel rounded-xl border border-warning/30 bg-warning/10 p-3 shadow-glow"
    : "mt-4 rounded-xl border border-warning/30 bg-warning/10 p-4 shadow-glow";

  const reasons = Object.entries(HITL_REASON) as Array<[string, HitlReasonValue]>;

  return (
    <section className={classShell} aria-label="HITL dev tools">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <div className="font-label text-[10px] font-bold uppercase tracking-wider text-warning">
            Dev
          </div>
          <div className="font-body text-xs text-on-surface-variant">
            Inject mock HITL state to preview panel UIs.
          </div>
        </div>
        <button
          type="button"
          className="btn-secondary text-[11px]"
          onClick={() => setWorkflow((prev) => (prev ? { ...prev, run: { ...prev.run, status: "RUNNING", requires_hitl: false, hitl_reason: "" }, state: { ...(prev.state ?? {}), workflow_status: "RUNNING", requires_hitl: false, hitl_reason: "", pending_hitl_options: [] } } : prev))}
          disabled={!workflow}
          title={!workflow ? "No workflow loaded" : "Reset injected HITL flags"}
        >
          Reset
        </button>
      </div>

      <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-[1fr_auto] sm:items-end">
        <label className="flex min-w-0 flex-col gap-1 font-body text-xs text-on-surface">
          <span className="font-label text-[10px] uppercase tracking-wider text-outline">
            hitl_reason
          </span>
          <select
            className="auteur-input h-9 w-full text-xs"
            defaultValue=""
            onChange={(e) => {
              const v = e.target.value as HitlReasonValue;
              if (!v) return;
              setWorkflow((prev) => buildNextWorkflow(prev, v));
              e.currentTarget.value = "";
            }}
          >
            <option value="">Select to inject…</option>
            {reasons.map(([key, value]) => (
              <option key={key} value={value}>
                {key}
              </option>
            ))}
          </select>
        </label>
        <div className="font-mono text-[10px] text-on-surface-variant">
          status → WAITING_HITL
        </div>
      </div>
    </section>
  );
}

