import type { HitlContextPayload } from "../../types";
import { HITL_REASON } from "./hitlCopy";

export type HitlTranslate = (key: string, fallback?: string, params?: Record<string, string | number>) => string;

function asRecord(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}

/** UI label for a pending_hitl_options id (falls back to server label, then id). */
export function mapHitlQuickActionLabel(optionId: string, serverLabel: string | undefined, t: HitlTranslate): string {
  const key = `hitl.option.${optionId}`;
  const v = t(key, "");
  if (v.trim() && v !== key) return v;
  const s = String(serverLabel ?? "").trim();
  return s || optionId;
}

export function mapHitlOptionHint(optionId: string, t: HitlTranslate): string {
  const key = `hitl.hint.${optionId}`;
  return t(key, "");
}

/** Single-line failure explanation for plan loop (message preferred over raw violation code). */
export function buildPlanLoopFailureLine(state: Record<string, unknown>, t: HitlTranslate): string | null {
  const pf = state.plan_feedback;
  if (!Array.isArray(pf) || pf.length === 0) return null;
  const last = pf[pf.length - 1];
  const row = asRecord(last);
  if (!row) return null;
  const msg = String(row.message ?? "").trim();
  if (msg) return `${t("hitl.planLoop.failurePrefix", "無法通過原因")}：${msg}`;
  const viol = String(row.violation ?? "").trim();
  if (viol) return `${t("hitl.planLoop.failurePrefix", "無法通過原因")}：${viol}`;
  return null;
}

function lastResolutionMethod(state: Record<string, unknown>): string {
  const rows = state.recent_chapter_summaries;
  if (!Array.isArray(rows) || rows.length === 0) return "";
  const last = rows[rows.length - 1];
  const r = asRecord(last);
  return String(r?.resolution_method ?? "").trim();
}

function lastEndingVibe(state: Record<string, unknown>): string {
  const rows = state.recent_chapter_summaries;
  if (!Array.isArray(rows) || rows.length === 0) return "";
  const last = rows[rows.length - 1];
  const r = asRecord(last);
  return String(r?.ending_vibe ?? "").trim();
}

/** Primary headline under HITL (PM copy); optional second line via `extraLine`. */
export function buildHitlPrimaryHeadline(
  reason: string,
  state: Record<string, unknown>,
  hitlContext: HitlContextPayload | null,
  t: HitlTranslate,
): { headline: string; extraLine: string | null } {
  switch (reason) {
    case HITL_REASON.PLAN_LOOP:
      return { headline: t("hitl.planLoop.headline"), extraLine: buildPlanLoopFailureLine(state, t) };
    case HITL_REASON.RESOLUTION_TACTIC: {
      const tactic = lastResolutionMethod(state) || t("hitl.resolutionTactic.tacticFallback");
      return { headline: t("hitl.resolutionTactic.headline", "", { tactic }), extraLine: null };
    }
    case HITL_REASON.ENDING_VIBE: {
      const vibe = lastEndingVibe(state) || t("hitl.endingVibe.vibeFallback");
      return { headline: t("hitl.endingVibe.headline", "", { vibe }), extraLine: null };
    }
    case HITL_REASON.B_STORY_COOLDOWN: {
      const name = pickBStoryCooldownName(state) || t("hitl.bStoryCooldown.nameFallback");
      const n = String(estimateBStoryStagnantChapters(state));
      return { headline: t("hitl.bStoryCooldown.headline", "", { name, n }), extraLine: null };
    }
    case HITL_REASON.DRAFT_LOOP:
      return { headline: t("hitl.draftLoop.headline"), extraLine: null };
    case HITL_REASON.OUTPUT_LANGUAGE:
      return { headline: t("hitl.outputLanguage.headline"), extraLine: null };
    case HITL_REASON.EXTRACTION_GATE:
      return { headline: t("hitl.extraction.headline"), extraLine: buildExtractionEntityLine(state, t) };
    case HITL_REASON.B_STORY: {
      const cand = asRecord(state.anchor_resolution_hitl_candidate ?? state.b_story_resolution_hitl_candidate);
      const name =
        (cand && (String(cand.anchor_title ?? cand.title ?? cand.name ?? "").trim() || String(cand.id ?? "").trim())) ||
        t("hitl.bStoryResolve.nameFallback");
      return { headline: t("hitl.bStoryResolve.headline", "", { name }), extraLine: null };
    }
    case HITL_REASON.CONTEXT: {
      const est = state.context_overflow_char_estimate;
      const n = est != null && Number.isFinite(Number(est)) ? String(est) : "—";
      return {
        headline: t("hitl.context.headline"),
        extraLine: t("hitl.context.estimate", "", { n }),
      };
    }
    case HITL_REASON.ALIGNMENT_RULES_REQUIRED: {
      const issue =
        String(hitlContext?.primary_issue ?? "").trim() ||
        String(state.alignment_log ?? "")
          .trim()
          .slice(0, 120) ||
        t("hitl.alignment.issueFallback");
      return { headline: t("hitl.alignment.headline", "", { issue }), extraLine: null };
    }
    default:
      return { headline: t("hitl.title"), extraLine: null };
  }
}

function pickBStoryCooldownName(state: Record<string, unknown>): string {
  const chosen = String(state.b_story_type ?? "").trim().toUpperCase();
  const stories = state.active_b_stories;
  if (Array.isArray(stories) && chosen) {
    for (const row of stories) {
      const r = asRecord(row);
      if (!r) continue;
      const typ = String(r.type ?? "").trim().toUpperCase();
      if (typ === chosen) {
        const id = String(r.id ?? "").trim();
        const desc = String(r.desc ?? "").trim();
        if (desc) return desc.slice(0, 80);
        if (id) return id;
      }
    }
  }
  const dir = String(state.b_story_directive ?? "").trim();
  if (dir) return dir.slice(0, 80);
  return "";
}

function estimateBStoryStagnantChapters(state: Record<string, unknown>): number {
  const recent = state.recent_b_story_types;
  if (Array.isArray(recent) && recent.length > 0) return Math.min(12, recent.length + 2);
  return 3;
}

function buildExtractionEntityLine(state: Record<string, unknown>, t: HitlTranslate): string | null {
  const hints = state.hitl_extraction_remap_hints;
  if (!Array.isArray(hints) || hints.length === 0) return null;
  const names: string[] = [];
  for (const h of hints.slice(0, 3)) {
    const r = asRecord(h);
    if (!r) continue;
    const pname = String(r.planned_canonical_name ?? "").trim();
    const mid = String(r.missing_planned_node_id ?? "").trim();
    const label = pname || mid;
    if (label) names.push(label);
  }
  if (!names.length) return null;
  return t("hitl.extraction.entitiesPrefix", "", { names: names.join("、") });
}

export function getRemapExpectedNodeType(missingPlannedNodeId: string, state: Record<string, unknown>): string | null {
  const id = missingPlannedNodeId.trim();
  if (!id) return null;
  const planned = state.planned_graph_nodes;
  if (!Array.isArray(planned)) return null;
  for (const row of planned) {
    const r = asRecord(row);
    if (!r) continue;
    if (String(r.node_id ?? "").trim() === id) {
      const nt = r.node_type;
      return nt != null && String(nt).trim() ? String(nt).trim() : null;
    }
  }
  return null;
}

export type ExtractionRemapRowModel = {
  missing_planned_node_id: string;
  planned_canonical_name: string;
  fromOptions: Array<{ node_id: string; label: string }>;
  defaultFromId: string;
};

/** Parse backend `build_extraction_remap_hints` rows for the HITL UI. */
export function parseExtractionRemapHints(hints: unknown): ExtractionRemapRowModel[] {
  if (!Array.isArray(hints)) return [];
  const out: ExtractionRemapRowModel[] = [];
  for (const h of hints) {
    const r = asRecord(h);
    if (!r) continue;
    const mid = String(r.missing_planned_node_id ?? "").trim();
    const pname = String(r.planned_canonical_name ?? "").trim();
    const candidates = Array.isArray(r.candidate_extracted) ? r.candidate_extracted : [];
    const fromOptions: Array<{ node_id: string; label: string }> = [];
    for (const c of candidates) {
      const cc = asRecord(c);
      if (!cc) continue;
      const nid = String(cc.node_id ?? "").trim();
      const cn = String(cc.canonical_name ?? "").trim();
      if (!nid) continue;
      fromOptions.push({ node_id: nid, label: cn ? `${cn} (${nid})` : nid });
    }
    if (!mid && fromOptions.length === 0) continue;
    out.push({
      missing_planned_node_id: mid,
      planned_canonical_name: pname,
      fromOptions,
      defaultFromId: fromOptions[0]?.node_id ?? "",
    });
  }
  return out;
}

export type GraphNodeLite = { node_id: string; node_type?: string; canonical_name?: string };

export function filterGraphNodesByType(nodes: GraphNodeLite[], nodeType: string | null): GraphNodeLite[] {
  if (!nodeType) return nodes;
  const t = nodeType.trim().toUpperCase();
  return nodes.filter((n) => String(n.node_type ?? "").trim().toUpperCase() === t);
}
