import { FLOW_STEPS, getStuckFlowStepIndex } from "./hitlCopy";

type Props = {
  reason: string;
  resumeFrom: string;
  compact?: boolean;
};

export function HitlFlowStrip({ reason, resumeFrom, compact }: Props) {
  const stuckIndex = getStuckFlowStepIndex(reason, resumeFrom);
  const steps = compact ? COMPACT_FLOW : FULL_FLOW;

  if (compact) {
    const cur = steps.find((s) => s.indices.includes(stuckIndex));
    const label = cur?.userLabel ?? FLOW_STEPS[stuckIndex]?.userLabel ?? "流程中";
    return (
      <div className="rounded-lg border border-outline-variant/15 bg-surface-container-highest/30 px-3 py-2">
        <p className="font-label text-[10px] uppercase tracking-wider text-on-surface-variant">目前停在哪一步</p>
        <p className="mt-0.5 font-body text-sm font-medium text-tertiary">{label}</p>
        <p className="mt-1 font-label text-[10px] text-on-surface-variant">
          完整步驟圖請在「主控台」檢視暫停面板。
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto pb-1">
      <ol className="flex min-w-max items-stretch gap-0">
        {steps.map((step, i) => {
          const isStuck = step.indices.includes(stuckIndex);
          const isPast = Math.min(...step.indices) < stuckIndex;
          return (
            <li key={step.userLabel} className="flex items-stretch">
              <div
                className={`flex max-w-[7.5rem] flex-col items-center px-1 text-center ${
                  isStuck
                    ? "text-tertiary"
                    : isPast
                      ? "text-on-surface-variant"
                      : "text-on-surface-variant/70"
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
                <span className="mt-1.5 font-label text-[10px] leading-tight">{step.userLabel}</span>
              </div>
              {i < steps.length - 1 ? (
                <div
                  className={`mt-4 h-px w-3 shrink-0 self-start ${
                    Math.min(...steps[i + 1].indices) <= stuckIndex ? "bg-primary/30" : "bg-outline-variant/20"
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

/** Collapsed labels for default horizontal strip */
const FULL_FLOW: { userLabel: string; indices: number[] }[] = [
  { userLabel: "章節方向", indices: [0] },
  { userLabel: "背景整理", indices: [1] },
  { userLabel: "規劃與審核", indices: [2, 3] },
  { userLabel: "撰寫與審稿", indices: [4, 5] },
  { userLabel: "閱讀檢查", indices: [6] },
  { userLabel: "設定歸檔", indices: [7] },
  { userLabel: "副線與完稿", indices: [8, 9] },
];

const COMPACT_FLOW: { userLabel: string; indices: number[] }[] = [
  { userLabel: "規劃階段", indices: [0, 1, 2, 3] },
  { userLabel: "撰寫階段", indices: [4, 5, 6] },
  { userLabel: "收尾階段", indices: [7, 8, 9] },
];
