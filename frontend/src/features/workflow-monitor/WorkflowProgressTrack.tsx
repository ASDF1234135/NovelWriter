import { FLOW_STEPS } from "../hitl-panel/hitlCopy";
import type { WorkflowPayload } from "../../types";
import { useI18n } from "../../i18n/useI18n";

type Props = {
  workflow: WorkflowPayload | null;
  compact?: boolean;
};

const STAGE_GROUPS = [
  {
    id: "planning",
    label: { "zh-Hant": "本章規劃", "zh-Hans": "本章规划", en: "Planning this chapter" },
    stepIds: ["director", "graph_rag", "planner", "plan_supervisor", "logic_alignment"],
  },
  {
    id: "writing",
    label: { "zh-Hant": "正文撰寫", "zh-Hans": "正文撰写", en: "Drafting prose" },
    stepIds: ["author", "draft_supervisor", "reader"],
  },
  {
    id: "archive",
    label: { "zh-Hant": "章末整理", "zh-Hans": "章末整理", en: "Chapter wrap-up" },
    stepIds: ["extraction_gate", "copyeditor", "output_language_gate", "chapter_summarizer"],
  },
  {
    id: "finish",
    label: { "zh-Hant": "確認並儲存", "zh-Hans": "确认并保存", en: "Confirm & save" },
    stepIds: ["anchor_resolve", "profile_expander", "state_updater", "commit_to_databases"],
  },
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
  const { locale } = useI18n();
  const activeIndex = getActiveStepIndex(workflow);
  const runFailed =
    workflow != null &&
    (String(workflow.state.workflow_status ?? workflow.run.status ?? "").toUpperCase() === "FAILED" ||
      String(workflow.run.status ?? "").toUpperCase() === "FAILED");
  const hitlWait =
    workflow != null &&
    (workflow.run.requires_hitl === true ||
      String(workflow.run.status ?? "").toUpperCase() === "WAITING_HITL" ||
      String(workflow.state.workflow_status ?? "").toUpperCase() === "WAITING_HITL");
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
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <p className="font-label text-[10px] font-bold uppercase tracking-wider text-secondary">
          {locale === "en" ? "Writing stages" : locale === "zh-Hans" ? "撰写阶段" : "撰寫階段"}
        </p>
        {runFailed ? (
          <span className="rounded border border-semantic-danger/40 bg-semantic-danger/10 px-2 py-0.5 font-label text-[9px] font-bold uppercase tracking-wide text-semantic-danger">
            {locale === "en" ? "Failed" : locale === "zh-Hans" ? "失败" : "失敗"}
          </span>
        ) : hitlWait ? (
          <span className="rounded border border-semantic-warning/40 bg-semantic-warning/10 px-2 py-0.5 font-label text-[9px] font-bold uppercase tracking-wide text-semantic-warning">
            {locale === "en" ? "HITL" : locale === "zh-Hans" ? "待人工" : "待人工"}
          </span>
        ) : null}
      </div>
      <ol className={`grid ${compact ? "grid-cols-2 gap-2" : "grid-cols-2 gap-3 md:grid-cols-4"}`}>
        {groups.map((group) => {
          const failedHere = runFailed && group.active;
          return (
            <li
              key={group.id}
              className={`rounded-lg border px-3 py-2 text-xs font-medium ${
                failedHere
                  ? "border-semantic-danger/50 bg-semantic-danger/15 text-semantic-danger"
                  : group.active
                    ? hitlWait
                      ? "border-semantic-warning/45 bg-semantic-warning/10 text-semantic-warning"
                      : "border-primary bg-primary/15 text-primary"
                    : group.done
                      ? "border-semantic-success/35 bg-semantic-success/10 text-semantic-success"
                      : "border-outline-variant/20 text-on-surface-variant"
              }`}
            >
              {group.done && !failedHere ? "✓ " : ""}
              {group.label[locale]}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
