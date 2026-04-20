from __future__ import annotations

from app.domain.schema import PlanSupervisorOutput, SuggestionType, ViolationType
from app.services.llm import MockLLMClient
from app.services.workflow.context import WorkflowContext
from app.services.workflow.masking import build_plan_supervisor_payload, compact_plan_supervisor_payload_for_prompt
from app.services.workflow.output_language import augment_profile_system_prompt
from app.services.workflow.policy_gates import run_semantic_gate
from app.services.workflow.profiles import get_profile

_PLAN_VIOLATION_FEEDBACK: list[tuple[ViolationType, str, tuple[str, ...]]] = [
    (
        ViolationType.WORD_COUNT_UNMATCH,
        "(System) target_word_count or beat/word budget violates hard bounds; adjust outline, beats, or target length.",
        ("target_word_count", "word count", "beats"),
    ),
    (
        ViolationType.INCONSISTENCY,
        "(System) Outline disagrees with ground-truth events, ordering, or continuity; align with ground_truth_events and prior context.",
        ("ground_truth_events", "causal chain", "temporal"),
    ),
    (
        ViolationType.ANCHOR_DIVERGENCE,
        "(System) narrative_script does not converge toward the target anchor or drifts too far; revise narrative_script.",
        ("anchor", "converge"),
    ),
    (
        ViolationType.PHYSICAL_CONFLICT,
        "(System) Plan conflicts with known space/causality; align with last_known_location and the event chain.",
        ("space", "causal", "location"),
    ),
    (
        ViolationType.POV_LEAK,
        "(System) Script treats non-public intel as reader-common knowledge; adjust narrative disclosure level.",
        ("POV", "public"),
    ),
    (
        ViolationType.MISSING_DIRECTIVE,
        "(System) Director hard requirements unmet (e.g. new elements missing from proposed_new_nodes); add them.",
        ("Director", "proposed_new", "element"),
    ),
]


def _ensure_plan_supervisor_feedback_covers_violations(output: PlanSupervisorOutput) -> PlanSupervisorOutput:
    if output.is_approved:
        return output
    violations = [v for v in output.violation_type if v != ViolationType.NONE]
    if not violations:
        return output
    feedback = output.feedback_to_agent.strip()
    extras: list[str] = []
    for vtype, snippet, skip_tokens in _PLAN_VIOLATION_FEEDBACK:
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


def run_plan_supervisor(state: dict, context: WorkflowContext) -> tuple[dict, dict]:
    payload = build_plan_supervisor_payload(state)
    if not isinstance(context.llm_client, MockLLMClient):
        profile = augment_profile_system_prompt(
            get_profile("plan_supervisor"), context.output_language, prompt_kind="audit"
        )
        prompt = _build_plan_supervisor_prompt(payload)
        structured_output, _ = context.llm_client.invoke_json(prompt, PlanSupervisorOutput, profile)
        output = _apply_deterministic_checks(structured_output, payload)
        output = _apply_semantic_policy_checks(output, payload, context)
        output = _ensure_plan_supervisor_feedback_covers_violations(output)
        data = output.model_dump(mode="json")
        if not data.get("soft_warnings"):
            data["soft_warnings"] = []
        return data, payload.model_dump(mode="json")

    violations: list[ViolationType] = []
    feedback: list[str] = []

    if not payload.ground_truth_events:
        violations.append(ViolationType.INCONSISTENCY)
        feedback.append("Missing ground_truth_events.")

    if payload.target_anchor_chapter is not None and payload.target_anchor_chapter < payload.current_chapter_id:
        violations.append(ViolationType.INCONSISTENCY)
        feedback.append(
            "Target anchor chapter is earlier than the current chapter; anchor state may be stale or workflow state inconsistent."
        )

    requires_anchor_completion = (
        payload.target_anchor_chapter is not None
        and payload.current_chapter_id >= payload.target_anchor_chapter
    )
    ct = str(payload.chapter_type or "PLOT_DRIVEN")
    dist = payload.distance_to_anchor
    strict_anchor = ct == "PLOT_DRIVEN" or (dist is not None and int(dist) <= 1)
    if (
        strict_anchor
        and requires_anchor_completion
        and payload.target_anchor_id
        and payload.target_anchor_id not in payload.narrative_script
    ):
        violations.append(ViolationType.ANCHOR_DIVERGENCE)
        feedback.append("narrative_script does not clearly converge toward the target anchor.")
    elif payload.partial_convergence_allowed and payload.target_anchor_id and strict_anchor:
        feedback.append(
            "Still in early chapters before a distant anchor; partial convergence is allowed—require consistent direction and working foreshadow only."
        )

    directive_violations, directive_feedback = _detect_directive_structural_violations(payload)
    violations.extend(v for v in directive_violations if v not in violations)
    feedback.extend(directive_feedback)

    wc_violations, wc_feedback = _detect_word_count_violations(payload)
    violations.extend(violation for violation in wc_violations if violation not in violations)
    feedback.extend(wc_feedback)
    sem_violations, sem_feedback = _deterministic_policy_signal_checks(payload)
    violations.extend(violation for violation in sem_violations if violation not in violations)
    feedback.extend(sem_feedback)

    output = PlanSupervisorOutput(
        is_approved=not violations,
        violation_type=violations or [ViolationType.NONE],
        suggestion_type=SuggestionType.MODIFY if violations else SuggestionType.NONE,
        feedback_to_agent=" ".join(feedback),
        anchor_achieved=bool(
            not violations
            and payload.target_anchor_id
            and requires_anchor_completion
            and strict_anchor
        ),
        soft_warnings=[],
    )
    data = output.model_dump(mode="json")
    return data, payload.model_dump(mode="json")


def _build_plan_supervisor_prompt(payload) -> str:
    compact_json = compact_plan_supervisor_payload_for_prompt(payload)
    return (
        "Audit the JSON payload using the rules below:\n"
        "1. If target_anchor_chapter > current_chapter_id, partial convergence is allowed.\n"
        "2. Partial convergence only requires correct direction, working foreshadow, and no hard physics/timeline/causality breaks.\n"
        "3. anchor_achieved=false is normal while a distant anchor is unfinished—never block solely for that.\n"
        "4. Only when current_chapter_id >= target_anchor_chapter should explicit anchor completion be the main bar.\n"
        "5. If chapter_target - current_chapter >= 2, do not reject just because the final anchor is not finished yet.\n"
        "5b. If chapter_type is CHARACTER_DRIVEN or WORLD_BUILDING, do not reject solely for 'not advancing the main anchor'; "
        "still reject for premature anchor reveals or hard causal breaks.\n"
        "5c. Hard (semantic): each Director new_elements_to_introduce item should have a semantic counterpart in proposed_new_nodes "
        "(aliases, role compression, org vs person OK); do not demand literal substring matches. Backend only enforces: "
        "when new elements are required, proposed_new_nodes must be non-empty.\n"
        "5c-b. If b_story_directive is non-empty and not the generic placeholder, judge whether narrative_script substantively weaves "
        "that subplot (motif, image, event, or emotional thread); do not require copying the director sentence. MISSING_DIRECTIVE if absent; pass if covered.\n"
        "5d. Soft: thin idle beats or early-anchor-solve risk may go to soft_warnings while is_approved=true if no other Hard issues.\n"
        "6. Chronological consistency (Hard): check previous_chapter_summary/recent_chapter_context vs this chapter's ground_truth_events. "
        "If the plan replays already-finished beats without a new state change, or implies a time rollback without explicit framing, reject with INCONSISTENCY.\n"
        "7. Teleportation / Location Paradox (semantic only): compare last_known_location vs chapter_start_location and read ground_truth_events + narrative_script. "
        "If locations clearly disconnect without plausible move/transition/time jump, reject with PHYSICAL_CONFLICT or INCONSISTENCY; "
        "if they are the same place/alias or transition is clear, do not false-positive.\n"
        "8. POV_LEAK if narrative_script treats secret actions, private discoveries, or impossible POV knowledge as public common knowledge.\n"
        "9. If the plan involves movement, the chapter-end effective position must be legible; unfalsifiable post-move locations are also issues.\n"
        "10. Word-count bounds: target_word_count must fall in chapter_word_min..chapter_word_max; else WORD_COUNT_UNMATCH.\n"
        "11. Beats vs words: if len(must_include_beats) * words_per_beat_floor clearly exceeds target_word_count, mark WORD_COUNT_UNMATCH and ask to raise words or merge beats.\n"
        "12. Script density vs words: if narrative_script is very short/vague but target_word_count is very high (or the reverse), WORD_COUNT_UNMATCH with guidance to rebalance.\n"
        "12b. Event granularity (Hard): ground_truth_events should be macro events; do not split continuous dialogue/fights into micro-actions. "
        "If the plan is over-fragmented, reject with INCONSISTENCY and instruct merging by goal/scene/outcome phase.\n"
        "(Backend already runs some deterministic checks; you cover edge cases.)\n"
        "13. Boundary / mandatory-entity conflict (Hard, reject only on clear conflict): think as the Author. "
        "Cross-check ending_boundary_rule, forbidden_next_scene_actions, chapter_end_location_hint with proposed_new_nodes "
        "(planned_graph_nodes for this chapter, mandatory: true) plus must_include_beats, narrative_script, ground_truth_events. "
        "If a mandatory entity can only naturally appear/interact AFTER this chapter's boundary so the Author cannot write it without overshooting, "
        "reject (is_approved=false), suggestion_type=MODIFY, violation_type INCONSISTENCY (self-contradictory outline) or PHYSICAL_CONFLICT (cannot land before boundary). "
        "feedback_to_agent must name node_id or beat, cite the conflicting boundary, and tell Planner to defer the entity, or relax/move ending_boundary_rule. "
        "If proposed_new_nodes is absent or there are no mandatory rows, do not invent checks.\n"
        "14. When ai_freedom_level=strict, outline_binding_mode=FULL, and chapter_outline is substantive: "
        "if narrative_script/ground_truth_events clearly contradict the human outline, mark Hard INCONSISTENCY; "
        "if the outline is tiny/keyword-only, prefer soft_warnings to avoid over-rejecting.\n"
        f"\nPayload:\n{compact_json}"
    )


def _apply_deterministic_checks(output: PlanSupervisorOutput, payload) -> PlanSupervisorOutput:
    directive_violations, directive_feedback = _detect_directive_structural_violations(payload)
    word_violations, word_feedback = _detect_word_count_violations(payload)
    violations = [*directive_violations, *word_violations]
    soft = list(output.soft_warnings or [])

    if not violations:
        prev_soft = list(output.soft_warnings or [])
        if soft != prev_soft:
            return output.model_copy(update={"soft_warnings": soft})
        return output

    merged_violations = [violation for violation in output.violation_type if violation != ViolationType.NONE]
    for violation in violations:
        if violation not in merged_violations:
            merged_violations.append(violation)
    merged_feedback = output.feedback_to_agent.strip()
    for message in [*directive_feedback, *word_feedback]:
        if message not in merged_feedback:
            merged_feedback = f"{merged_feedback} {message}".strip()

    return PlanSupervisorOutput(
        is_approved=False,
        violation_type=merged_violations or [ViolationType.NONE],
        suggestion_type=output.suggestion_type if output.suggestion_type != SuggestionType.NONE else SuggestionType.MODIFY,
        feedback_to_agent=merged_feedback,
        anchor_achieved=False if violations else output.anchor_achieved,
        soft_warnings=soft,
    )


def _detect_word_count_violations(payload) -> tuple[list[ViolationType], list[str]]:
    violations: list[ViolationType] = []
    feedback: list[str] = []
    tw = int(payload.target_word_count)
    low = int(payload.chapter_word_min)
    high = int(payload.chapter_word_max)
    if tw < low:
        violations.append(ViolationType.WORD_COUNT_UNMATCH)
        feedback.append(f"target_word_count={tw} is below the allowed minimum {low}; raise the count or simplify the outline.")
    if tw > high:
        violations.append(ViolationType.WORD_COUNT_UNMATCH)
        feedback.append(f"target_word_count={tw} is above the allowed maximum {high}; lower the count or simplify the outline.")
    beats = payload.must_include_beats or []
    per = int(payload.words_per_beat_floor)
    needed = len(beats) * per
    if beats and needed > tw:
        violations.append(ViolationType.WORD_COUNT_UNMATCH)
        feedback.append(
            f"Word budget {tw} is incompatible with {len(beats)} must_include_beats (rough floor ~{needed}, {per} per beat); "
            "raise target_word_count or merge/remove beats."
        )
    script = (payload.narrative_script or "").strip()
    if len(script) < 80 and tw > 5000:
        violations.append(ViolationType.WORD_COUNT_UNMATCH)
        feedback.append("narrative_script is very short but target_word_count is high; lower words or enrich narrative_script.")
    return violations, feedback


def _non_empty_new_element_items(items: list) -> bool:
    for x in items or []:
        if isinstance(x, dict):
            if str(x.get("need") or "").strip() or str(x.get("reason") or "").strip():
                return True
        elif str(x or "").strip():
            return True
    return False


def _detect_directive_structural_violations(payload) -> tuple[list[ViolationType], list[str]]:
    """Python-only structural check: if Director asked for new elements, Planner must propose at least one node."""
    violations: list[ViolationType] = []
    feedback: list[str] = []
    proposed = payload.proposed_new_nodes or []
    has_element_request = _non_empty_new_element_items(payload.new_elements_to_introduce)
    if has_element_request and len(proposed) == 0:
        violations.append(ViolationType.MISSING_DIRECTIVE)
        feedback.append("Director required new elements but proposed_new_nodes is empty; add graph nodes.")
    for node in proposed:
        if not isinstance(node, dict):
            continue
        if str(node.get("node_type") or "") != "CHARACTER":
            continue
        prof = node.get("character_profile")
        if not isinstance(prof, dict):
            violations.append(ViolationType.MISSING_DIRECTIVE)
            feedback.append("CHARACTER node is missing character_profile; fill fields aligned with macro cast.")
            continue
        if not str(prof.get("core_motivation") or "").strip():
            violations.append(ViolationType.MISSING_DIRECTIVE)
            feedback.append("CHARACTER.character_profile.core_motivation must be non-empty.")
        if not str(prof.get("fatal_flaw") or "").strip():
            violations.append(ViolationType.MISSING_DIRECTIVE)
            feedback.append("CHARACTER.character_profile.fatal_flaw must be non-empty.")
        if not str(prof.get("speech_style") or "").strip():
            violations.append(ViolationType.MISSING_DIRECTIVE)
            feedback.append("CHARACTER.character_profile.speech_style must be non-empty.")
    seeds = getattr(payload, "new_active_b_stories", None) or []
    for seed in seeds:
        if not isinstance(seed, dict):
            continue
        if str(seed.get("id") or "").strip() and not str(seed.get("resolution_condition") or "").strip():
            violations.append(ViolationType.MISSING_DIRECTIVE)
            feedback.append(f"B-story {seed.get('id')} is missing resolution_condition; add an objective completion criterion.")
    return violations, feedback


def _deterministic_policy_signal_checks(payload) -> tuple[list[ViolationType], list[str]]:
    """Mock fallback for semantic policy checks."""
    violations: list[ViolationType] = []
    feedback: list[str] = []
    cooldown = getattr(payload, "resolution_cooldown_constraint", None) or {}
    narrative = str(getattr(payload, "narrative_script", "") or "")
    if cooldown.get("active") and any(
        k in narrative.lower() for k in ("mental duel", "mind link", "neural hack", "精神連結", "神經駭入", "腦機")
    ):
        violations.append(ViolationType.MISSING_DIRECTIVE)
        feedback.append(
            "RESOLUTION_COOLDOWN_HARD_VIOLATION: this chapter's plan still uses a banned resolution path; pivot to physical, environmental, negotiation, or kinetic violence."
        )
    vibe = getattr(payload, "ending_vibe_cooldown_constraint", None) or {}
    boundary = str(getattr(payload, "ending_boundary_rule", "") or "")
    if vibe.get("active") and (
        "安全屋" in boundary
        or "密室" in boundary
        or "總結對話" in narrative
        or "safe house" in boundary.casefold()
        or "locked room" in boundary.casefold()
        or "debrief dialogue" in narrative.casefold()
    ):
        violations.append(ViolationType.MISSING_DIRECTIVE)
        feedback.append(
            "ENDING_VIBE_COOLDOWN_HARD_VIOLATION: chapter ending still reads as SAFE_ROOM_EXPOSITION; pivot to ACTION_CLIFFHANGER."
        )
    return violations, feedback


def _apply_semantic_policy_checks(
    output: PlanSupervisorOutput, payload, context: WorkflowContext
) -> PlanSupervisorOutput:
    violations = [v for v in output.violation_type if v != ViolationType.NONE]
    feedback = output.feedback_to_agent.strip()
    narrative = str(getattr(payload, "narrative_script", "") or "")
    boundary = str(getattr(payload, "ending_boundary_rule", "") or "")
    cooldown = getattr(payload, "resolution_cooldown_constraint", None) or {}
    if cooldown.get("active"):
        gate, _ = run_semantic_gate(
            context=context,
            profile_name="plan_supervisor",
            rule_id="plan_resolution_cooldown",
            fallback_decision="allow",
            prompt=(
                "Check if the plan truly uses a banned resolution path.\n"
                "Block only when narrative relies on mind-link/neural-hack/mental-duel style forbidden resolution.\n"
                "Return JSON decision allow/warn/block with evidence_snippet and rationale.\n\n"
                f"narrative_script={narrative[:2500]}"
            ),
        )
        if gate.decision == "block":
            if ViolationType.MISSING_DIRECTIVE not in violations:
                violations.append(ViolationType.MISSING_DIRECTIVE)
            msg = "RESOLUTION_COOLDOWN_HARD_VIOLATION: semantic policy check confirms banned resolution path."
            if msg not in feedback:
                feedback = f"{feedback} {msg}".strip()
    vibe = getattr(payload, "ending_vibe_cooldown_constraint", None) or {}
    if vibe.get("active"):
        gate2, _ = run_semantic_gate(
            context=context,
            profile_name="plan_supervisor",
            rule_id="plan_ending_vibe_cooldown",
            fallback_decision="allow",
            prompt=(
                "Check whether chapter ending reads as SAFE_ROOM_EXPOSITION (forbidden vibe).\n"
                "Block only when ending really resolves into safe-room debrief style.\n"
                "Return JSON decision allow/warn/block with evidence_snippet and rationale.\n\n"
                f"ending_boundary_rule={boundary[:1000]}\n"
                f"narrative_script={narrative[:2500]}"
            ),
        )
        if gate2.decision == "block":
            if ViolationType.MISSING_DIRECTIVE not in violations:
                violations.append(ViolationType.MISSING_DIRECTIVE)
            msg = "ENDING_VIBE_COOLDOWN_HARD_VIOLATION: semantic policy check confirms forbidden ending vibe."
            if msg not in feedback:
                feedback = f"{feedback} {msg}".strip()
    if not violations:
        return output
    return output.model_copy(
        update={
            "is_approved": False,
            "violation_type": violations,
            "suggestion_type": output.suggestion_type if output.suggestion_type != SuggestionType.NONE else SuggestionType.MODIFY,
            "feedback_to_agent": feedback,
        }
    )


 
