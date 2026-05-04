import { useI18n } from "../../i18n/useI18n";
import type { MacroCompileData } from "../../types";

type AnchorNode = NonNullable<MacroCompileData["anchor_nodes"]>[number];

type Props = {
  storyId: string | null;
  setupSelectedAnchorNode: AnchorNode | null | undefined;
  selectedResolved: boolean;
  topologyLocked: boolean;
  dagFieldsEditable: boolean;
  busy: boolean;
  selectedAnchorLockedParentIds: string[];
  onPatchAnchor: (patch: Partial<AnchorNode>) => void;
};

export function SetupAnchorDagDetailPanel({
  storyId,
  setupSelectedAnchorNode,
  selectedResolved,
  topologyLocked,
  dagFieldsEditable,
  busy,
  selectedAnchorLockedParentIds,
  onPatchAnchor,
}: Props) {
  const { t, locale } = useI18n();
  const listSep = locale === "en" ? ", " : "、";

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div className="border-b border-outline-variant/15 px-3 py-2">
        <p className="text-xs font-semibold text-on-surface-variant">{t("app.dagDetail.heading")}</p>
      </div>
      <div className="space-y-3 p-3">
        {!storyId ? (
          <p className="rounded-lg bg-amber-500/10 px-2 py-1.5 text-[11px] text-amber-100/90">{t("app.dagDetail.needStory")}</p>
        ) : null}
        {setupSelectedAnchorNode && selectedResolved ? (
          <p className="rounded-lg border border-emerald-400/25 bg-emerald-950/25 px-2 py-1.5 text-[11px] text-emerald-100/90">
            {t("app.dagDetail.resolvedReadonly")}
          </p>
        ) : null}
        {topologyLocked ? (
          <p className="rounded-lg border border-outline-variant/20 px-2 py-1.5 text-[11px] text-on-surface-variant">
            {t("app.dagDetail.topologyLocked")}
          </p>
        ) : null}
        {setupSelectedAnchorNode ? (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            <label className="text-xs text-on-surface-variant">
              {t("app.dagDetail.nodeId")}
              <input
                value={String(setupSelectedAnchorNode.id)}
                disabled
                className="mt-1 w-full rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
              />
            </label>
            <label className="text-xs text-on-surface-variant">
              {t("app.dagDetail.dependsOn")}
              <input
                value={(setupSelectedAnchorNode.depends_on ?? []).join(", ")}
                disabled
                className="mt-1 w-full rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
              />
            </label>
            <label className="text-xs text-on-surface-variant">
              {t("app.dagDetail.status")}
              {String(setupSelectedAnchorNode.status ?? "LOCKED").toUpperCase() === "RESOLVED" ? (
                <input
                  value={t("app.dagDetail.statusResolved")}
                  disabled
                  className="mt-1 w-full rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
                />
              ) : (
                <select
                  value={String(setupSelectedAnchorNode.status ?? "LOCKED").toUpperCase() === "UNLOCKED" ? "UNLOCKED" : "LOCKED"}
                  onChange={(e) => {
                    const v = e.target.value === "UNLOCKED" ? "UNLOCKED" : "LOCKED";
                    onPatchAnchor({ status: v });
                  }}
                  disabled={!dagFieldsEditable || busy}
                  className="mt-1 w-full rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
                >
                  <option value="LOCKED">{t("app.dagDetail.statusLocked")}</option>
                  <option value="UNLOCKED" disabled={selectedAnchorLockedParentIds.length > 0}>
                    {t("app.dagDetail.statusUnlocked")}
                  </option>
                </select>
              )}
              {dagFieldsEditable &&
              selectedAnchorLockedParentIds.length > 0 &&
              String(setupSelectedAnchorNode.status ?? "").toUpperCase() !== "RESOLVED" ? (
                <p className="mt-1.5 text-[10px] leading-snug text-amber-200/90">
                  {t("app.dagDetail.parentLockedHint", undefined, {
                    parents: selectedAnchorLockedParentIds.join(listSep),
                  })}
                </p>
              ) : null}
            </label>
            <label className="text-xs text-on-surface-variant">
              {t("app.dagDetail.title")}
              <input
                value={String(setupSelectedAnchorNode.title ?? "")}
                onChange={(e) => onPatchAnchor({ title: e.target.value })}
                disabled={!dagFieldsEditable || busy}
                className="mt-1 w-full rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
              />
            </label>
            <label className="text-xs text-on-surface-variant md:col-span-2">
              {t("app.dagDetail.description")}
              <textarea
                value={String(setupSelectedAnchorNode.description ?? "")}
                onChange={(e) => onPatchAnchor({ description: e.target.value })}
                disabled={!dagFieldsEditable || busy}
                rows={3}
                className="mt-1 w-full resize-y rounded-lg border border-outline-variant/25 bg-surface-container-highest px-3 py-2 text-sm"
              />
            </label>
          </div>
        ) : null}
      </div>
    </div>
  );
}
