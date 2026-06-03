from __future__ import annotations

import json
import re

from app.domain.schema import DraftSupervisorOutput, LengthAdjustment, SuggestionType, ViolationType
from app.services.workflow.identity_rules import (
    extract_identity_tokens,
    is_low_risk_identity_label,
    looks_like_identity_rule,
)
from app.services.llm import MockLLMClient
from app.services.workflow.context import WorkflowContext
from app.services.workflow.masking import build_draft_supervisor_payload
from app.services.workflow.output_language import augment_profile_system_prompt
from app.services.workflow.policy_gates import HardGateResult, run_semantic_gate
from app.services.workflow.profiles import get_profile
from app.services.workflow.utils import chapter_content_length
from app.services.workflow.utils import (
    suggest_nearest_surface_candidates,
    surface_form_match_with_fallback,
)

_DRAFT_VIOLATION_FEEDBACK: list[tuple[ViolationType, str, tuple[str, ...]]] = [
    (
        ViolationType.WORD_COUNT_UNMATCH,
        "(System) Draft length is outside this chapter's allowed range; expand or compress to fit.",
        ("normalized", "allowed range"),
    ),
    (
        ViolationType.INCONSISTENCY,
        "(System) Draft disagrees with narrative_script, ground_truth_events, or the event chain; align on-page outcomes and facts with those sources.",
        ("boundary", "overshoot", "narrative_script", "does not track", "ground_truth", "event chain"),
    ),
    (
        ViolationType.PHYSICAL_CONFLICT,
        "(System) Hard clash with known world state, causality, or spatial continuity; align with bible/graph context.",
        ("physics", "causal", "continuity"),
    ),
    (
        ViolationType.ANCHOR_DIVERGENCE,
        "(System) This chapter's direction may make the target anchor unreachable or clearly off-plan; narrow the chapter mission.",
        ("anchor", "diverge"),
    ),
    (
        ViolationType.POV_LEAK,
        "(System) Possible impossible-POV intel written as public fact; adjust POV or disclosure framing.",
        ("POV", "leak", "private"),
    ),
    (
        ViolationType.MISSING_DIRECTIVE,
        "(System) Director/plan hard directives unmet (e.g. new elements not embodied); add the missing content.",
        ("Director", "directive", "materialize"),
    ),
    (
        ViolationType.MISSING_MANDATORY_ENTITY_MAPPING,
        "(System) Mandatory entities are not identifiable in prose or cannot align to planned nodes; add extractable surface forms and hints.",
        ("mandatory", "surface", "substring"),
    ),
    (
        ViolationType.INCONSISTENCY,
        "(System) Beats appear rushed: add on-page transitions (reaction, body state, dialogue) before outcomes; avoid plot-summary chaining.",
        ("plot rush", "teleport", "transition", "summary chaining"),
    ),
    (
        ViolationType.INCONSISTENCY,
        "(System) Character psychology or speech does not match active_character_profiles without on-page motivation.",
        ("personality", "speech_style", "out of character", "motivation"),
    ),
]


def _ensure_feedback_covers_violations(output: DraftSupervisorOutput) -> DraftSupervisorOutput:
    """Append deterministic lines when the model flagged violations but gave empty or vague feedback."""
    if output.is_approved:
        return output
    violations = [v for v in output.violation_type if v != ViolationType.NONE]
    if not violations:
        return output
    feedback = output.feedback_to_agent.strip()
    extras: list[str] = []
    for vtype, snippet, skip_tokens in _DRAFT_VIOLATION_FEEDBACK:
        if vtype not in violations:
            continue
        if snippet in feedback:
            continue
        if any(tok in feedback for tok in skip_tokens):
            continue
        extras.append(snippet)
    if not extras:
        return output
    merged = f"{feedback} {' '.join(extras)}".strip()
    return output.model_copy(update={"feedback_to_agent": merged})


def _length_bounds(payload) -> tuple[int, int]:
    lo = int(payload.normalized_length_min or 0)
    hi = int(payload.normalized_length_max or 0)
    if lo <= 0 or hi <= 0:
        tw = int(payload.target_word_count or 0)
        lo = int(tw * 0.65)
        hi = int(tw * 1.35)
    return lo, hi


def _mandatory_hints_violation(state: dict, payload) -> str:
    """Require each mandatory entity to have non-empty validated surface_forms in author hints."""
    draft = payload.current_draft or ""
    mandatory = payload.mandatory_new_entities or []
    if not mandatory:
        return ""
    hints_raw = state.get("author_extraction_surface_hints") or []
    hints_by_id = {
        str(h.get("node_id", "")).strip(): h
        for h in hints_raw
        if isinstance(h, dict) and str(h.get("node_id", "")).strip()
    }
    missing: list[str] = []
    diagnostics: list[str] = []
    for ent in mandatory:
        nid = ent.node_id
        entry = hints_by_id.get(nid)
        if not entry:
            missing.append(nid)
            diagnostics.append(f"{nid}: missing node_id entry in author_extraction_surface_hints")
            continue
        surfaces: list[str] = []
        raw_surfaces = [s for s in (entry.get("surface_forms") or []) if isinstance(s, str) and s]
        for s in (entry.get("surface_forms") or []):
            if not isinstance(s, str) or not s:
                continue
            if surface_form_match_with_fallback(s, draft):
                surfaces.append(s)
        if not surfaces:
            missing.append(nid)
            sample = raw_surfaces[:3]
            nearest: list[str] = []
            if sample:
                nearest = suggest_nearest_surface_candidates(sample[0], draft, limit=2)
            diag = f"{nid}: expected one of {sample or ['(none)']}"
            if nearest:
                diag += f"; nearest in draft: {nearest}"
            diagnostics.append(diag)
    if not missing:
        return ""
    hints_note = json.dumps(hints_raw, ensure_ascii=False)[:1200]
    return (
        "Mandatory entities lack validated surface forms (exact substrings): "
        + ", ".join(missing)
        + ". Write extractable in-text names and ensure author_extraction_surface_hints include exact substrings that appear in the draft. "
        + (f"Diagnostics: {' | '.join(diagnostics[:4])}. " if diagnostics else "")
        + f"Current author_extraction_surface_hints (excerpt): {hints_note}"
    )


def run_draft_supervisor(state: dict, context: WorkflowContext) -> tuple[dict, dict]:
    payload = build_draft_supervisor_payload(state)
    lang = str(state.get("story_output_language") or "")
    normalized_count = chapter_content_length(payload.current_draft, lang)
    lower, upper = _length_bounds(payload)

    hint_fail = _mandatory_hints_violation(state, payload)
    if hint_fail:
        gate = HardGateResult(
            rule_id="mandatory_hints_presence",
            passed=False,
            evidence_snippet=hint_fail[:220],
            rationale="Mandatory entity extraction surface forms missing in draft hints.",
        )
        out = DraftSupervisorOutput(
            is_approved=False,
            violation_type=[ViolationType.MISSING_MANDATORY_ENTITY_MAPPING],
            suggestion_type=SuggestionType.REWRITE,
            feedback_to_agent=hint_fail,
            length_adjustment=LengthAdjustment.NONE,
        )
        data = out.model_dump(mode="json")
        data.update(gate.model_dump(mode="json"))
        return data, payload.model_dump(mode="json")

    jargon_fail = _jargon_pruning_violation(payload)
    if jargon_fail:
        if isinstance(context.llm_client, MockLLMClient):
            out = DraftSupervisorOutput(
                is_approved=False,
                violation_type=[ViolationType.INCONSISTENCY],
                suggestion_type=SuggestionType.REWRITE,
                feedback_to_agent=jargon_fail,
                length_adjustment=LengthAdjustment.NONE,
            )
            data = out.model_dump(mode="json")
            data.update(
                HardGateResult(
                    gate_source="hybrid",
                    rule_id="draft_jargon_density",
                    passed=False,
                    confidence=0.75,
                    evidence_snippet=jargon_fail[:220],
                    rationale="Mock fallback: deterministic jargon signal.",
                ).model_dump(mode="json")
            )
            return data, payload.model_dump(mode="json")
        gate, _ = run_semantic_gate(
            context=context,
            profile_name="draft_supervisor",
            rule_id="draft_jargon_density",
            fallback_decision="allow",
            prompt=(
                "Decide whether this draft should be BLOCKED for machine-like jargon overuse.\n"
                "Block ONLY when jargon naming materially harms readability and sounds like disposable labels.\n"
                "Return JSON: decision allow/warn/block, confidence 0..1, evidence_snippet, rationale.\n\n"
                f"Draft:\n{(payload.current_draft or '')[:3500]}"
            ),
        )
        if gate.decision == "block":
            out = DraftSupervisorOutput(
                is_approved=False,
                violation_type=[ViolationType.INCONSISTENCY],
                suggestion_type=SuggestionType.REWRITE,
                feedback_to_agent=jargon_fail,
                length_adjustment=LengthAdjustment.NONE,
            )
            data = out.model_dump(mode="json")
            data.update(gate.model_dump(mode="json"))
            return data, payload.model_dump(mode="json")

    identity_fail = _identity_reveal_violation(state, payload)
    if identity_fail:
        if not isinstance(context.llm_client, MockLLMClient):
            gate, _ = run_semantic_gate(
                context=context,
                profile_name="draft_supervisor",
                rule_id="identity_reveal_semantic_confirm",
                fallback_decision="allow",
                prompt=(
                    "You are verifying identity-reveal policy.\n"
                    "Block ONLY if the draft explicitly maps/reveals true identity that is disallowed this chapter.\n"
                    "Mentions of labels/codes without identity mapping should be allow.\n"
                    "Return JSON: decision allow/warn/block, confidence 0..1, evidence_snippet, rationale.\n\n"
                    f"forbidden_reveals={state.get('forbidden_reveals')}\n"
                    f"allowed_identity_reveals_this_chapter={state.get('allowed_identity_reveals_this_chapter')}\n"
                    f"draft={(payload.current_draft or '')[:3500]}\n"
                ),
            )
            if gate.decision != "block":
                identity_fail = ""
        out = DraftSupervisorOutput(
            is_approved=not bool(identity_fail),
            violation_type=[ViolationType.POV_LEAK] if identity_fail else [ViolationType.NONE],
            suggestion_type=SuggestionType.REWRITE if identity_fail else SuggestionType.NONE,
            feedback_to_agent=identity_fail or "",
            length_adjustment=LengthAdjustment.NONE if identity_fail else _resolve_length_adjustment(normalized_count, lower, upper),
        )
        if identity_fail:
            data = out.model_dump(mode="json")
            data.update(
                HardGateResult(
                    gate_source="hybrid",
                    rule_id="identity_reveal_guard",
                    passed=False,
                    confidence=0.9,
                    evidence_snippet=identity_fail[:220],
                    rationale="Deterministic identity token hit confirmed by hybrid gate.",
                ).model_dump(mode="json")
            )
            return data, payload.model_dump(mode="json")

    if not isinstance(context.llm_client, MockLLMClient):
        profile = augment_profile_system_prompt(
            get_profile("draft_supervisor"), context.output_language, prompt_kind="audit"
        )
        prompt = _build_draft_supervisor_prompt(payload)
        structured_output, _ = context.llm_client.invoke_json(prompt, DraftSupervisorOutput, profile)
        output = _apply_word_count_gate(structured_output, normalized_count, lower, upper)
        output = _ensure_feedback_covers_violations(output)
        return output.model_dump(mode="json"), payload.model_dump(mode="json")

    violations: list[ViolationType] = []
    feedback: list[str] = []
    if normalized_count < lower or normalized_count > upper:
        violations.append(ViolationType.WORD_COUNT_UNMATCH)
        feedback.append(f"Normalized length {normalized_count} is outside the allowed range {lower}-{upper}.")

    # Mock author drafts may remain localized while planner narrative_script is English—do not apply the
    # naive substring gate here (real draft_supervisor still evaluates alignment via the LLM path).

    # Skip deterministic boundary cue matching under MockLLMClient: English planner forbidden lines tokenize
    # into common words that frequently appear in mock author prose, causing false INCONSISTENCY loops.
    boundary_feedback = ""

    output = DraftSupervisorOutput(
        is_approved=not violations,
        violation_type=violations or [ViolationType.NONE],
        suggestion_type=SuggestionType.MODIFY if violations else SuggestionType.NONE,
        feedback_to_agent=" ".join(feedback),
        length_adjustment=_resolve_length_adjustment(normalized_count, lower, upper),
    )
    return output.model_dump(mode="json"), payload.model_dump(mode="json")


def _apply_word_count_gate(
    output: DraftSupervisorOutput,
    normalized_count: int,
    lower: int,
    upper: int,
) -> DraftSupervisorOutput:
    if lower <= normalized_count <= upper:
        return output.model_copy(update={"length_adjustment": LengthAdjustment.NONE})

    violations = [violation for violation in output.violation_type if violation != ViolationType.NONE]
    if ViolationType.WORD_COUNT_UNMATCH not in violations:
        violations.append(ViolationType.WORD_COUNT_UNMATCH)
    feedback = output.feedback_to_agent.strip()
    message = f"Normalized length {normalized_count} is outside the allowed range {lower}-{upper}."
    if message not in feedback:
        feedback = f"{feedback} {message}".strip()

    return DraftSupervisorOutput(
        is_approved=False,
        violation_type=violations,
        suggestion_type=output.suggestion_type if output.suggestion_type != SuggestionType.NONE else SuggestionType.MODIFY,
        feedback_to_agent=feedback,
        length_adjustment=_resolve_length_adjustment(normalized_count, lower, upper),
    )


def _build_draft_supervisor_prompt(payload) -> str:
    lo, hi = _length_bounds(payload)
    return (
        "Review ONLY the current draft version; ignore historical rejections.\n"
        f"The backend deterministically enforces length; allowed normalized_length is {lo}–{hi} (from state, same gate as Author).\n"
        "If the draft is short, keep suggestion_type at MODIFY and set length_adjustment to EXPAND; if too long, mark COMPRESS.\n"
        "Use PHYSICAL_CONFLICT or INCONSISTENCY only for clear hard conflicts; "
        "normal novelistic expansion, sensory writing, mood layering, and symbolic repetition are not violations; "
        "on-tone mundane detail, interiority, and micro-beats (drinks, weather, etc.) must not be treated as contradictions.\n"
        "When checking inconsistencies against ground_truth_events, evaluate the underlying narrative outcome and on-page actions, not literal dialogue: "
        "characters may lie, be sarcastic, or hide true motives in speech as long as what they do matches the recorded events.\n"
        "In feedback_to_agent: do NOT quote or restate ending_boundary_rule, forbidden_next_scene_actions, or other boundary text unless the draft explicitly violates them; "
        "if a rule is not violated, do not mention it.\n"
        "Mandatory-entity presence is already decided by author_extraction_surface_hints (exact substrings); "
        "do NOT judge MISSING_MANDATORY_ENTITY_MAPPING yourself.\n"
        "If partial_convergence_allowed=true, a distant anchor not being explicitly completed is NOT grounds for rejection; "
        "use ANCHOR_DIVERGENCE only when this draft makes future anchors unreachable.\n"
        "Use POV_LEAK when secret actions, private discoveries, or impossible-POV knowledge are written as public common knowledge.\n"
        "If the draft involves movement, the reader must be able to tell where the character left, arrived, or stayed; "
        "an unfalsifiable end-of-chapter position can also be an issue.\n"
        "If the draft is overloaded with stiff jargon, gamified proper nouns, or 'quotes + label naming' that could be natural sensory prose, "
        "treat it as INCONSISTENCY and demand rewrite.\n"
        "Do NOT nitpick minor staging details or sensory descriptions. If the draft captures the essence and narrative purpose of a 'must_include_beat', treat it as satisfied even if the exact physical action (e.g., looking through a window vs. standing on a landing) differs slightly—but the beat still needs a visible transition, not a single summary sentence. Do NOT output rule reminders for rules that were NOT violated.\n"
        "## Character and pacing audit (mirror Author)\n"
        "R1 Opening: after high-impact prior chapter, opening needs observable emotional/body residue unless continuity notes say recovered.\n"
        "R2 Logistics: major moves/fights/persuasion must show who/where/how/obstacles; reject logistics teleport vs graph_context/bible_context/locations.\n"
        "R3 Psychology: major decisions need at least one beat of perception→emotion/body→action; reject personality snap vs active_character_profiles without earned pressure.\n"
        "R4 Plot-rush: reject stacked 'then/next/finally' result sentences between beats without reactions; reject time skips that skip required on-page beats; reject narrative_script paraphrase as prose.\n"
        "R5 Ending: ending_state_shift must come from on-page process, not a closing declaration only.\n"
        "feedback_to_agent must name the missing transition type (body/emotion/dialogue/obstacle), not vague 'push plot harder.'\n"
        "When chapter_end_location_hint, ending_boundary_rule, or forbidden_next_scene_actions are defined, "
        "treat them as hard boundaries; writing past the boundary into entry, meetings, hard scene changes, new bases, or premature reveals is INCONSISTENCY.\n"
        "Return a single JSON object.\n\n"
        f"{payload.model_dump_json(indent=2)}"
    )


def _jargon_pruning_violation(payload) -> str:
    draft = (payload.current_draft or "").strip()
    if not draft:
        return ""
    quoted_terms = re.findall(r"「([^」]{2,30})」", draft)
    suspicious_quoted = [
        t
        for t in quoted_terms
        if ("：" in t or ":" in t)
        or any(
            k in t
            for k in (
                "節點",
                "邏輯",
                "協同",
                "模組",
                "矩陣",
                "協議",
                "模式",
                "演算",
                "緩衝",
                "node",
                "matrix",
                "protocol",
                "buffer",
                "module",
                "stack",
            )
        )
    ]
    jargon_tokens = (
        "節點",
        "協同邏輯",
        "緩衝節點",
        "戰術模組",
        "策略模組",
        "演算",
        "協議棧",
        "tactical module",
        "strategy module",
        "protocol stack",
    )
    jargon_hits = sum(draft.count(tok) for tok in jargon_tokens)
    if len(suspicious_quoted) < 2 and jargon_hits < 3:
        return ""
    samples = ", ".join(suspicious_quoted[:3]) if suspicious_quoted else "(high jargon density)"
    return (
        "The draft overuses disposable proper nouns / label-like naming, hurting readability. "
        f"Detected samples: {samples}. "
        "Rewrite into natural narration: keep factual causality, but break gimmick terms into observable action, sensation, and outcome."
    )


def _extract_boundary_cues(action: str) -> list[str]:
    raw_parts = [part.strip() for part in action.replace("，", " ").replace("、", " ").replace("。", " ").split() if part.strip()]
    cues: list[str] = []
    for part in raw_parts:
        normalized = part
        for prefix in (
            "不要",
            "不可",
            "不得",
            "避免",
            "本章",
            "提前",
            "do not ",
            "must not ",
            "cannot ",
            "avoid ",
            "this chapter ",
            "prematurely ",
        ):
            normalized = normalized.removeprefix(prefix)
        normalized = normalized.strip()
        if len(normalized) >= 3:
            cues.append(normalized)
    return cues


def _resolve_length_adjustment(normalized_count: int, lower: int, upper: int) -> LengthAdjustment:
    if normalized_count < lower:
        return LengthAdjustment.EXPAND
    if normalized_count > upper:
        return LengthAdjustment.COMPRESS
    return LengthAdjustment.NONE


def _identity_reveal_violation(state: dict, payload) -> str:
    draft = str(payload.current_draft or "")
    if not draft.strip():
        return ""
    allowed = {
        str(x).strip().casefold()
        for x in (state.get("allowed_identity_reveals_this_chapter") or [])
        if str(x).strip()
    }
    violations: list[str] = []
    for rule in (state.get("forbidden_reveals") or []):
        if not isinstance(rule, str) or not rule.strip():
            continue
        if not looks_like_identity_rule(rule):
            continue
        for token in extract_identity_tokens(rule):
            if is_low_risk_identity_label(token):
                continue
            if token.casefold() in allowed:
                continue
            if re.search(re.escape(token), draft, flags=re.IGNORECASE):
                violations.append(token)
    if not violations:
        return ""
    terms = "、".join(sorted(set(violations))[:5])
    return (
        "Draft contains identity reveals not allowed this chapter: "
        f"{terms}. Rewrite to reader-visible layers without explicit true-identity mapping."
    )


