import { useEffect, useRef } from "react";
import type { WorkflowPayload } from "../../types";
import { useI18n } from "../../i18n/useI18n";
import {
  routeDecisionLabel,
  workflowAgentStepLabel,
  workflowRunStatusLabel,
} from "../ui-copy/workflowDisplay";

type Props = {
  workflow: WorkflowPayload | null;
  variant?: "default" | "compact";
};

function redactVerboseState(
  state: WorkflowPayload["state"],
): WorkflowPayload["state"] {
  const out = { ...(state ?? {}) };
  delete out.anchor_candidates;
  delete out.resolved_anchors;
  delete out.llm_weave_debug;
  return out;
}

function redactUnknownPayload(value: unknown): unknown {
  if (Array.isArray(value)) return value.map((item) => redactUnknownPayload(item));
  if (value && typeof value === "object") {
    const row = value as Record<string, unknown>;
    const out: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(row)) {
      if (key === "llm_weave_debug") continue;
      out[key] = redactUnknownPayload(item);
    }
    return out;
  }
  return value;
}

export function AgentOutputView({ workflow, variant = "default" }: Props) {
  const { locale } = useI18n();
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
      <h2 className="mb-3 font-headline text-sm font-bold uppercase tracking-wider text-secondary">
        {locale === "en" ? "Run Logs" : locale === "zh-Hans" ? "撰写过程记录" : "撰寫過程紀錄"}
      </h2>
      {!workflow ? (
        <p className="font-body text-sm text-on-surface-variant">
          {locale === "en" ? "No execution logs yet." : locale === "zh-Hans" ? "尚无执行记录。" : "尚無執行紀錄。"}
        </p>
      ) : (
        <>
          <p className="mb-3 font-label text-xs text-on-surface-variant">
            {locale === "en" ? "Run " : locale === "zh-Hans" ? "执行编号 " : "執行編號 "}
            <span className="font-mono text-on-surface">{workflow.run.run_id}</span> · {locale === "en" ? `Chapter ${workflow.run.chapter_id}` : `第 ${workflow.run.chapter_id} 章`} ·{" "}
            <strong className="text-on-surface">{workflowRunStatusLabel(workflow.run.status)}</strong>
            {workflow.run.current_agent ? (
              <>
                {" "}
                · {locale === "en" ? "Current step " : locale === "zh-Hans" ? "当前步骤 " : "目前步驟 "}
                <strong className="text-primary">{workflowAgentStepLabel(workflow.run.current_agent)}</strong>
              </>
            ) : null}{" "}
            · {locale === "en" ? `${stepCount} steps` : locale === "zh-Hans" ? `共 ${stepCount} 个步骤` : `共 ${stepCount} 個步驟`}
          </p>
          {compact ? (
            <div className="max-h-36 overflow-y-auto no-scrollbar">
              {workflow.steps.slice(-3).map((step) => (
                <div key={step.step_id} className="mb-2 rounded-lg bg-surface-container-highest/50 p-2 font-mono text-[10px] text-on-surface-variant">
                  {locale === "en" ? `Step ${step.step_index}` : locale === "zh-Hans" ? `第 ${step.step_index} 步` : `第 ${step.step_index} 步`} ·{" "}
                  {workflowAgentStepLabel(step.agent_name)}
                </div>
              ))}
              <div ref={stepsEndRef} />
            </div>
          ) : (
            <div className="grid min-w-0 gap-4">
              <article className="min-w-0">
                <h3 className="mb-2 font-headline text-xs font-bold text-primary">
                  {locale === "en" ? "Current State (Full)" : locale === "zh-Hans" ? "当前状态（完整）" : "目前狀態（完整）"}
                </h3>
                <pre className="auteur-pre max-h-[320px] max-w-full overflow-auto whitespace-pre-wrap break-all text-xs">
                  {JSON.stringify(redactVerboseState(workflow.state), null, 2)}
                </pre>
              </article>
              <article className="min-w-0">
                <h3 className="mb-2 font-headline text-xs font-bold text-primary">
                  {locale === "en" ? "Step List" : locale === "zh-Hans" ? "步骤列表" : "步驟列表"}
                </h3>
                <p className="mb-2 font-body text-xs text-on-surface-variant">
                  {locale === "en" ? "Auto-updates while connected." : locale === "zh-Hans" ? "连线时会自动更新。" : "連線時會自動更新。"}
                </p>
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
                          {locale === "en" ? `Step ${step.step_index}` : locale === "zh-Hans" ? `第 ${step.step_index} 步` : `第 ${step.step_index} 步`} · {workflowAgentStepLabel(step.agent_name)} · {locale === "en" ? "Route" : locale === "zh-Hans" ? "分支" : "分支"}：{branch} · {statusZh}
                        </summary>
                        <pre className="auteur-pre mt-2 max-h-[280px] max-w-full overflow-auto whitespace-pre-wrap break-all text-[11px]">
                          {JSON.stringify(redactUnknownPayload(step.output_payload_json), null, 2)}
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
