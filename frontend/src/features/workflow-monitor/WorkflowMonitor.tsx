import type { WorkflowPayload } from "../../types";
import { resumeNodeUserLabel as resumeLabelFromHitl } from "../hitl-panel/hitlCopy";
import {
  hitlReasonTitle,
  workflowAgentStepLabel,
  workflowInternalStatusLabel,
  workflowRunStatusLabel,
} from "../ui-copy/workflowDisplay";

type Props = {
  workflow: WorkflowPayload | null;
  variant?: "default" | "compact";
};

function resumeDisplay(resumeFrom: string): string {
  const raw = String(resumeFrom ?? "").trim();
  if (!raw) return "—";
  return resumeLabelFromHitl(raw);
}

export function WorkflowMonitor({ workflow, variant = "default" }: Props) {
  const compact = variant === "compact";
  const shell = compact
    ? "glass-panel rounded-xl border border-outline-variant/15 p-4 shadow-glow"
    : "rounded-xl border border-outline-variant/10 bg-surface-container-low p-6 shadow-glow";

  if (!workflow) {
    return (
      <section className={shell}>
        <h2 className="mb-2 font-headline text-sm font-bold uppercase tracking-wider text-primary">章節撰寫進度</h2>
        <p className="font-body text-sm text-on-surface-variant">尚未開始本章的自動撰寫流程。</p>
      </section>
    );
  }

  const state = workflow.state;
  const agentRaw =
    workflow.run.current_agent ?? (typeof state.last_agent === "string" ? state.last_agent : null) ?? "";
  const hitlReasonRaw = String(state.hitl_reason ?? workflow.run.hitl_reason ?? "").trim();

  return (
    <section className={shell}>
      <h2 className="mb-4 flex items-center gap-2 font-headline text-sm font-bold uppercase tracking-wider text-primary">
        <span className="material-symbols-outlined text-base">monitoring</span>
        {compact ? "本次執行" : "章節撰寫進度"}
      </h2>
      <div className={`grid gap-3 ${compact ? "grid-cols-1 text-xs" : "grid-cols-2 md:grid-cols-4"}`}>
        <div>
          <div className="font-label text-[10px] uppercase tracking-wider text-outline">執行編號</div>
          <div className="break-all font-mono text-on-surface">{workflow.run.run_id}</div>
        </div>
        <div>
          <div className="font-label text-[10px] uppercase tracking-wider text-outline">目前步驟</div>
          <div className="text-on-surface">{workflowAgentStepLabel(agentRaw)}</div>
        </div>
        <div>
          <div className="font-label text-[10px] uppercase tracking-wider text-outline">狀態</div>
          <div className="text-on-surface">{workflowRunStatusLabel(workflow.run.status)}</div>
          {!compact ? (
            <div className="text-xs text-on-surface-variant">
              內部狀態：{workflowInternalStatusLabel(String(state.workflow_status ?? "-"))}
            </div>
          ) : null}
        </div>
        <div>
          <div className="font-label text-[10px] uppercase tracking-wider text-outline">章節</div>
          <div className="text-on-surface">{workflow.run.chapter_id}</div>
        </div>
      </div>
      {!compact ? (
        <div className="mt-4 flex flex-wrap gap-3 border-t border-outline-variant/10 pt-4 font-label text-xs text-on-surface-variant">
          <span>視角角色：{String(state.pov_character_id ?? "-")}</span>
          <span>時間段：{String(state.active_epoch_id ?? "-")}</span>
          <span>目標里程碑：{String(state.target_anchor_id ?? "-")}</span>
          <span>閱讀評分：{String(state.last_reader_score ?? "-")}</span>
          <span>暫停原因：{hitlReasonRaw ? hitlReasonTitle(hitlReasonRaw) : "—"}</span>
          <span>接續位置：{resumeDisplay(String(state.resume_from ?? ""))}</span>
        </div>
      ) : null}
    </section>
  );
}
