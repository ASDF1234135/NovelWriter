import { useDeferredValue, useEffect, useMemo, useRef } from "react";
import type { WorkflowPayload } from "../../types";
import { useI18n } from "../../i18n/useI18n";
import { workflowAgentStepLabel, workflowRunStatusLabel } from "../ui-copy/workflowDisplay";

type Props = {
  workflow: WorkflowPayload | null;
  variant?: "default" | "compact";
};

const JSON_CLIP_CHARS = 24_000;

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

function clipJson(value: unknown): string {
  try {
    const s = JSON.stringify(value, null, 2);
    if (s.length <= JSON_CLIP_CHARS) return s;
    return `${s.slice(0, JSON_CLIP_CHARS)}\n… [truncated ${s.length - JSON_CLIP_CHARS} chars]`;
  } catch {
    return String(value);
  }
}

export function AgentOutputView({ workflow, variant = "default" }: Props) {
  const { locale } = useI18n();
  const stepsEndRef = useRef<HTMLDivElement>(null);
  const compact = variant === "compact";
  const deferredWorkflow = useDeferredValue(workflow);
  const displayWorkflow = compact ? workflow : deferredWorkflow;
  const stepCount = workflow?.steps.length ?? 0;

  const clippedStateJson = useMemo(
    () => (displayWorkflow ? clipJson(redactVerboseState(displayWorkflow.state)) : ""),
    [displayWorkflow],
  );

  const clippedStepPayloads = useMemo(() => {
    if (!displayWorkflow?.steps.length) return [];
    return displayWorkflow.steps.map((step) => ({
      step_id: step.step_id,
      agent_name: step.agent_name,
      status: step.status,
      payloadJson: clipJson(redactUnknownPayload(step.output_payload_json)),
    }));
  }, [displayWorkflow]);

  useEffect(() => {
    stepsEndRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [stepCount]);

  const shell = compact
    ? "glass-panel max-h-64 overflow-hidden rounded-xl border border-outline-variant/15 p-4 shadow-glow"
    : "rounded-xl border border-outline-variant/10 bg-surface-container-low p-6 shadow-glow";

  const title =
    locale === "en" ? "Run Logs" : locale === "zh-Hans" ? "撰写过程记录" : "撰寫過程紀錄";
  const emptyMsg =
    locale === "en" ? "No execution logs yet." : locale === "zh-Hans" ? "尚无执行记录。" : "尚無執行紀錄。";
  const stepsHeading =
    locale === "en" ? "Steps" : locale === "zh-Hans" ? "撰写步骤" : "撰寫步驟";
  const stepsHint =
    locale === "en"
      ? "Updates automatically while connected."
      : locale === "zh-Hans"
        ? "连线时会自动更新。"
        : "連線時會自動更新。";
  const stateSummary =
    locale === "en"
      ? "Full workflow data (advanced)"
      : locale === "zh-Hans"
        ? "完整流程资料（进阶）"
        : "完整流程資料（進階）";
  const technicalSummary =
    locale === "en"
      ? "Technical details"
      : locale === "zh-Hans"
        ? "技术详情"
        : "技術詳情";
  const runIdLabel = locale === "en" ? "Run ID" : locale === "zh-Hans" ? "执行编号" : "執行編號";
  const chapterLabel = locale === "en" ? "Chapter" : locale === "zh-Hans" ? "章节" : "章節";
  const currentStepLbl =
    locale === "en" ? "Current step" : locale === "zh-Hans" ? "当前步骤" : "目前步驟";
  const stepCountLbl =
    locale === "en"
      ? `${stepCount} step${stepCount === 1 ? "" : "s"}`
      : locale === "zh-Hans"
        ? `共 ${stepCount} 步`
        : `共 ${stepCount} 步`;

  return (
    <section className={`${shell} min-w-0`}>
      <h2 className="mb-3 font-headline text-sm font-bold uppercase tracking-wider text-secondary">{title}</h2>
      {!workflow ? (
        <p className="font-body text-sm text-on-surface-variant">{emptyMsg}</p>
      ) : (
        <>
          <p className="mb-2 font-label text-xs text-on-surface-variant">
            {chapterLabel}{" "}
            <strong className="text-on-surface">
              {locale === "en" ? `Chapter ${workflow.run.chapter_id}` : `第 ${workflow.run.chapter_id} 章`}
            </strong>
            {" · "}
            <strong className="text-on-surface">{workflowRunStatusLabel(workflow.run.status)}</strong>
            {workflow.run.current_agent ? (
              <>
                {" · "}
                {currentStepLbl}{" "}
                <strong className="text-primary">{workflowAgentStepLabel(workflow.run.current_agent)}</strong>
              </>
            ) : null}
            {" · "}
            {stepCountLbl}
          </p>
          {!compact ? (
            <details className="mb-3 rounded-lg border border-outline-variant/15 bg-surface-container-lowest/60 px-3 py-2">
              <summary className="cursor-pointer font-label text-xs text-primary">{technicalSummary}</summary>
              <p className="mt-2 font-mono text-[10px] leading-relaxed text-on-surface-variant">
                <span className="font-label text-on-surface-variant">{runIdLabel}: </span>
                {workflow.run.run_id}
              </p>
            </details>
          ) : null}
          {compact ? (
            <div className="max-h-36 overflow-y-auto no-scrollbar">
              {workflow.steps.slice(-3).map((step) => (
                <div
                  key={step.step_id}
                  className="mb-2 rounded-lg bg-surface-container-highest/50 p-2 font-body text-[11px] text-on-surface-variant"
                >
                  <span className="text-on-surface">{workflowAgentStepLabel(step.agent_name)}</span>
                  {" · "}
                  <span>{workflowRunStatusLabel(step.status)}</span>
                </div>
              ))}
              <div ref={stepsEndRef} />
            </div>
          ) : (
            <div className="grid min-w-0 gap-4">
              <article className="min-w-0">
                <h3 className="mb-2 font-headline text-xs font-bold text-primary">{stepsHeading}</h3>
                <p className="mb-2 font-body text-xs text-on-surface-variant">{stepsHint}</p>
                <div className="max-h-[420px] min-w-0 space-y-2 overflow-auto pr-1">
                  {clippedStepPayloads.map((row, index) => {
                    const isLatest = index === clippedStepPayloads.length - 1;
                    const statusLabel = workflowRunStatusLabel(row.status);
                    return (
                      <details
                        key={row.step_id}
                        open={isLatest}
                        className="rounded-lg border border-outline-variant/15 bg-surface-container-lowest/80 px-2 py-1"
                      >
                        <summary
                          className={`cursor-pointer font-label text-xs ${isLatest ? "text-primary" : "text-on-surface-variant"}`}
                        >
                          {workflowAgentStepLabel(row.agent_name)} · {statusLabel}
                        </summary>
                        <pre className="auteur-pre mt-2 max-h-[280px] max-w-full overflow-auto whitespace-pre-wrap break-all text-[11px]">
                          {row.payloadJson}
                        </pre>
                      </details>
                    );
                  })}
                  <div ref={stepsEndRef} />
                </div>
              </article>
              <details className="min-w-0 rounded-lg border border-outline-variant/15 bg-surface-container-lowest/80">
                <summary className="cursor-pointer px-2 py-2 font-headline text-xs font-bold text-primary">
                  {stateSummary}
                </summary>
                <pre className="auteur-pre max-h-[320px] max-w-full overflow-auto whitespace-pre-wrap break-all px-2 pb-2 text-xs">
                  {clippedStateJson}
                </pre>
              </details>
            </div>
          )}
        </>
      )}
    </section>
  );
}
