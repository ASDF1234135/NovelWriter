import { useEffect, useRef } from "react";
import type { WorkflowPayload } from "../../types";

type Props = {
  workflow: WorkflowPayload | null;
};

export function AgentOutputView({ workflow }: Props) {
  const stepsEndRef = useRef<HTMLDivElement>(null);

  const stepCount = workflow?.steps.length ?? 0;
  useEffect(() => {
    stepsEndRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [stepCount]);

  return (
    <section className="panel">
      <h2>Agent 產出觀測窗</h2>
      {!workflow ? (
        <p>尚無工作流資料。</p>
      ) : (
        <>
          <p className="agent-output-meta muted">
            Run <span className="mono">{workflow.run.run_id}</span> · 章節 {workflow.run.chapter_id} · 狀態{" "}
            <strong>{workflow.run.status}</strong>
            {workflow.run.current_agent ? (
              <>
                {" "}
                · 目前節點 <strong>{workflow.run.current_agent}</strong>
              </>
            ) : null}
            · 已記錄步驟 <strong>{stepCount}</strong>
            {workflow.state?.workflow_status != null ? (
              <>
                {" "}
                · workflow_status <strong>{String(workflow.state.workflow_status)}</strong>
              </>
            ) : null}
          </p>
          <div className="output-grid">
            <article>
              <h3>最新 State</h3>
              <pre className="agent-state-pre">{JSON.stringify(workflow.state, null, 2)}</pre>
            </article>
            <article>
              <h3>Workflow Steps</h3>
              <p className="muted small-hint">每個 Agent 節點完成後會追加一筆；執行中請透過儀表板訂閱事件流自動刷新。</p>
              <div className="step-list">
                {workflow.steps.map((step, index) => {
                  const isLatest = index === workflow.steps.length - 1;
                  return (
                    <details key={step.step_id} open={isLatest} className={isLatest ? "step-latest" : ""}>
                      <summary>
                        #{step.step_index} {step.agent_name} | {step.route_decision || step.status}
                      </summary>
                      <pre>{JSON.stringify(step.output_payload_json, null, 2)}</pre>
                    </details>
                  );
                })}
                <div ref={stepsEndRef} />
              </div>
            </article>
          </div>
        </>
      )}
    </section>
  );
}
