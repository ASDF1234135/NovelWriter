import { useEffect, useRef } from "react";
import type { WorkflowPayload } from "../../types";
import {
  routeDecisionLabel,
  workflowAgentStepLabel,
  workflowRunStatusLabel,
} from "../ui-copy/workflowDisplay";

type Props = {
  workflow: WorkflowPayload | null;
  variant?: "default" | "compact";
};

export function AgentOutputView({ workflow, variant = "default" }: Props) {
  const stepsEndRef = useRef<HTMLDivElement>(null);
  const compact = variant === "compact";
  const stepCount = workflow?.steps.length ?? 0;

  useEffect(() => {
    stepsEndRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [stepCount]);

  const shell = compact
    ? "glass-panel max-h-64 overflow-hidden rounded-xl border border-outline-variant/15 p-4 shadow-glow"
    : "rounded-xl border border-outline-variant/10 bg-surface-container-low p-6 shadow-glow";

  return (
    <section className={`${shell} min-w-0`}>
      <h2 className="mb-3 font-headline text-sm font-bold uppercase tracking-wider text-secondary">撰寫過程紀錄</h2>
      {!workflow ? (
        <p className="font-body text-sm text-on-surface-variant">尚無執行紀錄。</p>
      ) : (
        <>
          <p className="mb-3 font-label text-xs text-on-surface-variant">
            執行編號 <span className="font-mono text-on-surface">{workflow.run.run_id}</span> · 第 {workflow.run.chapter_id} 章 ·{" "}
            <strong className="text-on-surface">{workflowRunStatusLabel(workflow.run.status)}</strong>
            {workflow.run.current_agent ? (
              <>
                {" "}
                · 目前步驟 <strong className="text-primary">{workflowAgentStepLabel(workflow.run.current_agent)}</strong>
              </>
            ) : null}{" "}
            · 共 {stepCount} 個步驟
          </p>
          {compact ? (
            <div className="max-h-36 overflow-y-auto no-scrollbar">
              {workflow.steps.slice(-3).map((step) => (
                <div key={step.step_id} className="mb-2 rounded-lg bg-surface-container-highest/50 p-2 font-mono text-[10px] text-on-surface-variant">
                  第 {step.step_index} 步 · {workflowAgentStepLabel(step.agent_name)}
                </div>
              ))}
              <div ref={stepsEndRef} />
            </div>
          ) : (
            <div className="grid min-w-0 gap-4">
              <article className="min-w-0">
                <h3 className="mb-2 font-headline text-xs font-bold text-primary">目前狀態（完整）</h3>
                <pre className="auteur-pre max-h-[320px] max-w-full overflow-auto whitespace-pre-wrap break-all text-xs">
                  {JSON.stringify(workflow.state, null, 2)}
                </pre>
              </article>
              <article className="min-w-0">
                <h3 className="mb-2 font-headline text-xs font-bold text-primary">步驟列表</h3>
                <p className="mb-2 font-body text-xs text-on-surface-variant">連線時會自動更新。</p>
                <div className="max-h-[420px] min-w-0 space-y-2 overflow-auto pr-1">
                  {workflow.steps.map((step, index) => {
                    const isLatest = index === workflow.steps.length - 1;
                    const branch = routeDecisionLabel(step.route_decision || "");
                    const statusZh = workflowRunStatusLabel(step.status);
                    return (
                      <details
                        key={step.step_id}
                        open={isLatest}
                        className="rounded-lg border border-outline-variant/15 bg-surface-container-lowest/80 px-2 py-1"
                      >
                        <summary className={`cursor-pointer font-label text-xs ${isLatest ? "text-primary" : "text-on-surface-variant"}`}>
                          第 {step.step_index} 步 · {workflowAgentStepLabel(step.agent_name)} · 分支：{branch} · {statusZh}
                        </summary>
                        <pre className="auteur-pre mt-2 max-h-[280px] max-w-full overflow-auto whitespace-pre-wrap break-all text-[11px]">
                          {JSON.stringify(step.output_payload_json, null, 2)}
                        </pre>
                      </details>
                    );
                  })}
                  <div ref={stepsEndRef} />
                </div>
              </article>
            </div>
          )}
        </>
      )}
    </section>
  );
}
