import { HitlPanelSection } from "./HitlPanelSection";
import { buildQuickActionConfirm } from "./hitlQuickConfirm";
import { mapHitlOptionHint, mapHitlQuickActionLabel, type HitlTranslate } from "./hitlNarrative";
import type { QuickActionItem } from "./hitlPanelLayout";

type PreviewPayload = {
  title: string;
  bullets: string[];
  confirmLabel: string;
  onConfirm: () => void;
};

type Props = {
  actions: QuickActionItem[];
  controlsLocked: boolean;
  t: HitlTranslate;
  onRequestPreview: (preview: PreviewPayload) => void;
  onExecuteQuickAction: (optionId: string) => void;
};

export function HitlPanelQuickSection({ actions, controlsLocked, t, onRequestPreview, onExecuteQuickAction }: Props) {
  if (actions.length === 0) return null;

  return (
    <HitlPanelSection sectionId="hitl-section-quick" title={t("hitl.section.quick")}>
      <div className="flex flex-col gap-2">
        {actions.map((option) => {
          const label = mapHitlQuickActionLabel(option.id, option.label, t);
          const hint = mapHitlOptionHint(option.id, t).trim();
          const confirm = buildQuickActionConfirm(option.id, option.label, t);
          return (
            <div
              key={option.id}
              className="rounded-lg border border-outline-variant/15 bg-surface-container-low/60 p-2 transition-colors hover:border-primary/25"
            >
              <button
                type="button"
                disabled={controlsLocked}
                onClick={() =>
                  onRequestPreview({
                    ...confirm,
                    onConfirm: () => onExecuteQuickAction(option.id),
                  })
                }
                className="w-full rounded-md bg-primary/12 px-3 py-2.5 text-left font-label text-sm font-medium text-primary transition-colors hover:bg-primary/22 disabled:opacity-40"
              >
                {label}
              </button>
              {hint ? <p className="mt-1.5 px-1 font-body text-xs leading-relaxed text-on-surface-variant">{hint}</p> : null}
            </div>
          );
        })}
      </div>
    </HitlPanelSection>
  );
}
