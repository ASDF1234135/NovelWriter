import type { WorkflowPayload } from "../../types";

type Props = {
  workflow: WorkflowPayload | null;
};

export function AgentOutputView({ workflow }: Props) {
  return (
    <section className="panel">
      <h2>Agent 產出觀測窗</h2>
      {!workflow ? (
        <p>尚無工作流資料。</p>
      ) : (
        <div className="output-grid">
          <article>
            <h3>最新 State</h3>
            <pre>{JSON.stringify(workflow.state, null, 2)}</pre>
          </article>
          <article>
            <h3>Workflow Steps</h3>
            <div className="step-list">
              {workflow.steps.map((step) => (
                <details key={step.step_id}>
                  <summary>
                    #{step.step_index} {step.agent_name} | {step.route_decision || step.status}
                  </summary>
                  <pre>{JSON.stringify(step.output_payload_json, null, 2)}</pre>
                </details>
              ))}
            </div>
          </article>
        </div>
      )}
    </section>
  );
}
