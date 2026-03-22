import type { WorkflowPayload } from "../../types";

type Props = {
  workflow: WorkflowPayload | null;
};

export function WorkflowMonitor({ workflow }: Props) {
  if (!workflow) {
    return (
      <section className="panel">
        <h2>全域進度追蹤</h2>
        <p>尚未啟動章節工作流。</p>
      </section>
    );
  }

  const state = workflow.state;

  return (
    <section className="panel">
      <h2>全域進度追蹤</h2>
      <div className="stats-grid">
        <div>
          <strong>Run ID</strong>
          <div>{workflow.run.run_id}</div>
        </div>
        <div>
          <strong>目前 Agent</strong>
          <div>{workflow.run.current_agent ?? "unknown"}</div>
        </div>
        <div>
          <strong>狀態</strong>
          <div>{workflow.run.status}</div>
        </div>
        <div>
          <strong>章節</strong>
          <div>Chapter {workflow.run.chapter_id}</div>
        </div>
      </div>
      <div className="progress-line">
        <span>POV: {String(state.pov_character_id ?? "-")}</span>
        <span>Epoch: {String(state.active_epoch_id ?? "-")}</span>
        <span>Anchor: {String(state.target_anchor_id ?? "-")}</span>
        <span>Reader Score: {String(state.last_reader_score ?? "-")}</span>
      </div>
    </section>
  );
}
