import { mapHitlOptionHint, mapHitlQuickActionLabel, type HitlTranslate } from "./hitlNarrative";

export type QuickConfirmPayload = {
  title: string;
  bullets: string[];
  confirmLabel: string;
};

export function buildQuickActionConfirm(
  optionId: string,
  serverLabel: string | undefined,
  t: HitlTranslate,
): QuickConfirmPayload {
  const label = mapHitlQuickActionLabel(optionId, serverLabel, t);
  const hint = mapHitlOptionHint(optionId, t).trim();

  if (optionId === "force_approve_plan") {
    return {
      title: t("hitl.preview.forceApproveTitle"),
      bullets: [t("hitl.preview.forceApproveBullet1"), t("hitl.preview.forceApproveBullet2")],
      confirmLabel: t("hitl.preview.forceApproveConfirm"),
    };
  }

  if (optionId === "anchor_force_resolve") {
    return {
      title: t("hitl.preview.anchorForceResolveTitle"),
      bullets: [t("hitl.preview.anchorForceResolveBullet1"), t("hitl.preview.anchorForceResolveBullet2")],
      confirmLabel: t("hitl.preview.anchorForceResolveConfirm"),
    };
  }

  if (optionId === "anchor_continue_unresolved") {
    return {
      title: t("hitl.preview.anchorContinueUnresolvedTitle"),
      bullets: [t("hitl.preview.anchorContinueUnresolvedBullet1"), t("hitl.preview.anchorContinueUnresolvedBullet2")],
      confirmLabel: t("hitl.preview.anchorContinueUnresolvedConfirm"),
    };
  }

  if (optionId === "anchor_rewrite") {
    return {
      title: t("hitl.preview.anchorRewriteTitle"),
      bullets: [t("hitl.preview.anchorRewriteBullet1"), t("hitl.preview.anchorRewriteBullet2")],
      confirmLabel: t("hitl.preview.anchorRewriteConfirm"),
    };
  }

  const bullets = hint ? [hint, t("hitl.preview.quickBulletDefault")] : [t("hitl.preview.quickBulletDefault")];

  return {
    title: t("hitl.preview.quickTitle", "", { action: label }),
    bullets,
    confirmLabel: t("hitl.preview.quickConfirm"),
  };
}
