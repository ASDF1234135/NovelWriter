from __future__ import annotations

import json
from typing import Any

from app.domain.schema import AlignmentOutput, HitlReason
from app.services.llm import MockLLMClient
from app.services.workflow.context import WorkflowContext
from app.services.workflow.output_language import augment_profile_system_prompt
from app.services.workflow.profiles import get_profile

LOGIC_ALIGN_BIBLE_CAP = 4500
LOGIC_ALIGN_GRAPH_CAP = 3500
LOGIC_ALIGN_VECTOR_CAP = 2500


def _clip(text: str, max_chars: int) -> str:
    t = str(text or "")
    return t if len(t) <= max_chars else t[:max_chars]


def _should_run_canon_audit(state: dict[str, Any]) -> bool:
    outline = str(state.get("chapter_outline") or state.get("author_chapter_plan") or "").strip()
    if len(outline) >= 20:
        return True
    if len(str(state.get("graph_context") or "").strip()) > 80:
        return True
    if len(str(state.get("bible_context") or "").strip()) > 80:
        return True
    if len(str(state.get("vector_context") or "").strip()) > 80:
        return True
    return False


def _build_logic_alignment_prompt(state: dict[str, Any]) -> str:
    hard_rules = str(state.get("chapter_hard_rules") or "")
    has_hard = bool(hard_rules.strip())
    pov = str(state.get("pov_character_id") or "")
    draft_script = str(state.get("narrative_script") or "")
    draft_beats = list(state.get("must_include_beats") or [])
    draft_events = list(state.get("ground_truth_events") or [])
    boundary = str(state.get("ending_boundary_rule") or "")
    forbidden = list(state.get("forbidden_reveals") or [])
    human_outline = str(state.get("chapter_outline") or state.get("author_chapter_plan") or "").strip()
    bible = _clip(str(state.get("bible_context") or ""), LOGIC_ALIGN_BIBLE_CAP)
    graph = _clip(str(state.get("graph_context") or ""), LOGIC_ALIGN_GRAPH_CAP)
    vector = _clip(str(state.get("vector_context") or ""), LOGIC_ALIGN_VECTOR_CAP)

    hard_block = (
        "## Verbatim chapter hard rules (preserve faithfully; redact impossible-POV spoilers before surfacing)\n"
        f"{_clip(hard_rules, 8000)}\n\n"
        if has_hard
        else (
            "## Verbatim chapter hard rules\n"
            "(The author did not supply chapter_hard_rules; do not invent rules. safe_chapter_rules may be empty.)\n\n"
        )
    )

    rules_priority = (
        "## Absolute priority when hard rules exist\n"
        "1) Hard rules override the draft.\n"
        "2) If the draft violates hard rules, revise final_* until compliant.\n"
        "3) If a root conflict cannot be repaired: drop the illegal beat and re-derive legal actions from the rules.\n\n"
        if has_hard
        else (
            "## When no hard rules are present\n"
            "- Default: keep final_ground_truth_events / final_narrative_script / final_must_include_beats aligned with the draft "
            "unless there is a **hard clash** with bible/graph/vector or the human outline and you can apply a **minimal necessary fix**.\n"
            "- Still populate human_outline_conflict_notes with any human-outline or draft vs canon evidence conflicts (or []).\n"
            "- Separate pure Planner invention issues vs human text that contradicts canon; the latter must be explicit in hitl_reason or conflict lines.\n"
            "- Irreconcilable core world-rule conflicts: requires_hitl=true.\n\n"
        )
    )

    pov_block = (
        "## POV information safety (when hard rules exist)\n"
        f"- Current POV: {pov}\n"
        "- Scan hard-rule text: if it contains omniscient facts impossible for the POV, replace with [REDACTED: POV_UNKNOWN] in safe_chapter_rules.\n\n"
        if has_hard
        else ""
    )

    weave_block = (
        "## Seamless weaving (when hard rules exist)\n"
        "- Turn enforceable rule detail into writable prompts and fold into final_must_include_beats.\n\n"
        if has_hard
        else ""
    )

    return (
        "You are the Logic Alignment agent: continuity auditor and deus-ex-machina interceptor.\n"
        "Compare the human outline + Planner draft against bible/graph/vector memory; contradictions, logic dead-ends, or unexplained rescues → HITL or repair.\n"
        "Whether the outline is human-written or Planner-filled, any breach of established evidence must appear in human_outline_conflict_notes—do not omit.\n\n"
        f"{rules_priority}"
        f"{pov_block}"
        f"{weave_block}"
        "## Canon and retrieval memory (mandatory cross-check)\n"
        f"- bible_context:\n{bible}\n\n"
        f"- graph_context:\n{graph}\n\n"
        f"- vector_context:\n{vector}\n\n"
        "## Human chapter outline (verbatim)\n"
        f"{_clip(human_outline, 2000) if human_outline else '(none)'}\n\n"
        "## Draft outline (to align)\n"
        f"- draft_ground_truth_events: {json.dumps(draft_events, ensure_ascii=False)[:6000]}\n"
        f"- draft_narrative_script:\n{_clip(draft_script, 8000)}\n\n"
        f"- draft_must_include_beats: {json.dumps(draft_beats, ensure_ascii=False)[:2000]}\n\n"
        f"{hard_block}"
        "## End-of-chapter boundary (reference)\n"
        f"{_clip(boundary, 800)}\n\n"
        "## Forbidden reveals (reference)\n"
        f"{json.dumps(forbidden, ensure_ascii=False)[:1200]}\n\n"
        "## Output requirements (JSON / AlignmentOutput)\n"
        "- human_outline_conflict_notes: string array describing each clash (human claim vs evidence source). Soft tension can live here; hard breaks should set requires_hitl.\n"
        "- alignment_log: brief rationale for edits; if unchanged, state that audit found no required fixes.\n"
        "- final_* must be Author-deliverable.\n\n"
        "## HITL red lines (alongside hard rules; if triggered, requires_hitl)\n"
        "1) Complex mind-game / gambling without executable hard-rule scaffolding.\n"
        "2) Puzzle-solving depends on mechanisms undefined this chapter.\n"
        "3) Deus ex machina: new powers/allies without setup and contradicting graph memory.\n"
        "4) Human outline **verbatim** deterministically contradicts bible/graph with no automatic reconciliation.\n"
        "5) Extreme morality / core death beats needing author confirmation.\n"
    )


def run_logic_alignment(
    state: dict,
    context: WorkflowContext,
) -> tuple[dict[str, Any], dict[str, Any], int, int]:
    hard_rules = str(state.get("chapter_hard_rules") or "").strip()

    if not hard_rules:
        if not _should_run_canon_audit(state):
            log = "Skipped: No hard rules and no canon-audit context."
            requires_hitl = False
            reason = None
            out: dict[str, Any] = {
                "safe_chapter_rules": "",
                "alignment_log": log,
                "human_outline_conflict_notes": [],
                "requires_hitl": requires_hitl,
                "hitl_reason": reason,
            }
            payload: dict[str, Any] = {
                "chapter_id": state.get("chapter_id"),
                "pov_character_id": state.get("pov_character_id"),
                "skipped": True,
                "complex_draft_detected": requires_hitl,
            }
            return out, payload, 0, 0

    payload = {
        "chapter_id": state.get("chapter_id"),
        "pov_character_id": state.get("pov_character_id"),
        "draft_ground_truth_events": list(state.get("ground_truth_events") or []),
        "draft_narrative_script": str(state.get("narrative_script") or ""),
        "draft_must_include_beats": list(state.get("must_include_beats") or []),
        "chapter_hard_rules": _clip(hard_rules, 8000),
        "chapter_outline": _clip(str(state.get("chapter_outline") or ""), 2000),
    }
    prompt = _build_logic_alignment_prompt(state)

    if isinstance(context.llm_client, MockLLMClient):
        out = AlignmentOutput(
            final_ground_truth_events=[],
            final_narrative_script=str(state.get("narrative_script") or ""),
            final_must_include_beats=list(state.get("must_include_beats") or []),
            safe_chapter_rules=hard_rules,
            alignment_log="Mock: passthrough (no rule enforcement).",
            human_outline_conflict_notes=[],
            requires_hitl=False,
            hitl_reason=None,
        ).model_dump(mode="json")
        return out, payload, 0, 0

    profile = augment_profile_system_prompt(get_profile("logic_alignment"), context.output_language)
    structured, res = context.llm_client.invoke_json(prompt, AlignmentOutput, profile)
    dumped = structured.model_dump(mode="json")
    if dumped.get("requires_hitl") and not dumped.get("hitl_reason"):
        dumped["hitl_reason"] = HitlReason.ALIGNMENT_RULES_REQUIRED
    return dumped, payload, res.token_usage, res.latency_ms
