import { FLOW_STEPS, getStuckFlowStepIndex } from "./hitlCopy";
import { useI18n } from "../../i18n/useI18n";

type Props = {
  reason: string;
  resumeFrom: string;
  compact?: boolean;
};

const FULL_FLOW: { labelKey: string; indices: number[] }[] = [
  { labelKey: "hitl.flowStrip.merged.chapterDirection", indices: [0] },
  { labelKey: "hitl.flowStrip.merged.background", indices: [1] },
  { labelKey: "hitl.flowStrip.merged.planAndReview", indices: [2, 3, 4] },
  { labelKey: "hitl.flowStrip.merged.writeAndEdit", indices: [5, 6] },
  { labelKey: "hitl.flowStrip.merged.reader", indices: [7] },
  { labelKey: "hitl.flowStrip.merged.wrapUp", indices: [8, 9, 10, 11] },
  { labelKey: "hitl.flowStrip.merged.confirmSave", indices: [12, 13, 14, 15] },
];

const COMPACT_FLOW: { labelKey: string; indices: number[] }[] = [
  { labelKey: "hitl.flowStrip.compact.planning", indices: [0, 1, 2, 3, 4] },
  { labelKey: "hitl.flowStrip.compact.writing", indices: [5, 6, 7] },
  { labelKey: "hitl.flowStrip.compact.finish", indices: [8, 9, 10, 11, 12, 13, 14, 15] },
];

export function HitlFlowStrip({ reason, resumeFrom, compact }: Props) {
  const { t } = useI18n();
  const stuckIndex = getStuckFlowStepIndex(reason, resumeFrom);
  const steps = compact ? COMPACT_FLOW : FULL_FLOW;

  if (compact) {
    const cur = steps.find((s) => s.indices.includes(stuckIndex));
    const stepId = FLOW_STEPS[stuckIndex]?.id;
    const fromStepKey = stepId ? `hitl.flowStep.${stepId}` : "";
    const label = cur
      ? t(cur.labelKey)
      : fromStepKey
        ? t(fromStepKey)
        : t("hitl.flowStrip.inPipeline");
    return (
      <div className="mb-3 rounded-lg border border-outline-variant/15 bg-surface-container-highest/30 px-3 py-2">
        <p className="font-label text-[10px] uppercase tracking-wider text-on-surface-variant">{t("hitl.flowStrip.pausedAt")}</p>
        <p className="mt-0.5 font-body text-sm font-medium text-tertiary">{label}</p>
        <p className="mt-1 font-label text-[10px] text-on-surface-variant">{t("hitl.flowStrip.fullPipelineHint")}</p>
      </div>
    );
  }

  return (
    <div className="mb-3 overflow-x-auto pb-1">
      <ol className="flex min-w-max items-stretch gap-0">
        {steps.map((step, i) => {
          const isStuck = step.indices.includes(stuckIndex);
          const isPast = Math.min(...step.indices) < stuckIndex;
          const label = t(step.labelKey);
          return (
            <li key={step.labelKey} className="flex items-stretch">
              <div
                className={`flex max-w-[7.5rem] flex-col items-center px-1 text-center ${
                  isStuck ? "text-tertiary" : isPast ? "text-on-surface-variant" : "text-on-surface-variant/70"
                }`}
              >
                <span
                  className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full font-label text-xs font-bold ${
                    isStuck
                      ? "bg-tertiary text-on-tertiary ring-2 ring-tertiary/40"
                      : isPast
                        ? "bg-primary/20 text-primary"
                        : "bg-surface-container-highest text-on-surface-variant"
                  }`}
                  aria-current={isStuck ? "step" : undefined}
                >
                  {i + 1}
                </span>
                <span className="mt-1.5 font-label text-[10px] leading-tight">{label}</span>
              </div>
              {i < steps.length - 1 ? (
                <div
                  className={`mt-4 h-px w-3 shrink-0 self-start ${
                    Math.min(...(steps[i + 1]?.indices ?? [0])) <= stuckIndex ? "bg-primary/30" : "bg-outline-variant/20"
                  }`}
                  aria-hidden
                />
              ) : null}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
