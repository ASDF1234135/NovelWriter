import { FLOW_STEPS } from "../hitl-panel/hitlCopy";
import type { WorkflowPayload } from "../../types";

type Props = {
  workflow: WorkflowPayload | null;
  compact?: boolean;
};

const STAGE_GROUPS = [
  { id: "planning", label: "規劃", stepIds: ["director", "graph_rag", "planner", "plan_supervisor", "logic_alignment"] },
  { id: "writing", label: "撰寫", stepIds: ["author", "draft_supervisor", "reader"] },
  { id: "archive", label: "歸檔", stepIds: ["extraction_gate"] },
  { id: "finish", label: "收尾", stepIds: ["b_story_resolve", "state_updater"] },
] as const;

function getActiveStepIndex(workflow: WorkflowPayload | null): number {
  if (!workflow) return -1;
  const currentAgent = String(workflow.run.current_agent ?? workflow.state.last_agent ?? "").trim();
  if (currentAgent) {
    const idx = FLOW_STEPS.findIndex((s) => s.id === currentAgent);
    if (idx >= 0) return idx;
  }
  const status = String(workflow.state.workflow_status ?? workflow.run.status ?? "");
  if (status === "COMPLETED") return FLOW_STEPS.length - 1;
  if (status === "FAILED") return Math.max(FLOW_STEPS.length - 2, 0);
  return 0;
}

export function WorkflowProgressTrack({ workflow, compact = false }: Props) {
  const activeIndex = getActiveStepIndex(workflow);
  const groups = STAGE_GROUPS.map((group) => {
    const indexes = group.stepIds
      .map((id) => FLOW_STEPS.findIndex((step) => step.id === id))
      .filter((idx) => idx >= 0);
    const groupStart = Math.min(...indexes);
    const done = activeIndex > Math.max(...indexes);
    const active = activeIndex >= groupStart && activeIndex <= Math.max(...indexes);
    return { ...group, done, active };
  });

  return (
    <section className={`rounded-xl border border-outline-variant/15 bg-surface-container-low/60 ${compact ? "p-3" : "p-4"}`}>
      <p className="mb-2 font-label text-[10px] font-bold uppercase tracking-wider text-secondary">Workflow Progress</p>
      <ol className={`grid ${compact ? "grid-cols-2 gap-2" : "grid-cols-2 gap-3 md:grid-cols-4"}`}>
        {groups.map((group) => (
          <li
            key={group.id}
            className={`rounded-lg border px-3 py-2 text-xs font-medium ${
              group.active
                ? "border-primary bg-primary/15 text-primary"
                : group.done
                  ? "border-secondary/40 bg-secondary/10 text-secondary"
                  : "border-outline-variant/20 text-on-surface-variant"
            }`}
          >
            {group.done ? "✓ " : ""}
            {group.label}
          </li>
        ))}
      </ol>
    </section>
  );
}
