from __future__ import annotations

from typing import Any, NotRequired, TypedDict

from pydantic import BaseModel, Field

from app.domain.schema import (
    AiFreedomLevel,
    BeatOutline,
    BStoryType,
    ChapterType,
    EndingVibe,
    EventOutline,
    HitlDecisionMode,
    LengthAdjustment,
    MandatoryNewEntity,
    WorkflowStatus,
)

STATE_DEPRECATED_FIELDS: frozenset[str] = frozenset(
    {
        "author_chapter_plan",
    }
)

# Removal catalog for next-stage cleanup planning.
LOW_RISK_REMOVABLE_STATE_FIELDS: frozenset[str] = frozenset({"manual_override_payload", "b_story_route"})
MEDIUM_RISK_MIGRATION_FIELDS: frozenset[str] = frozenset({"author_chapter_plan"})
HIGH_RISK_CONTROL_STATE_FIELDS: dict[str, str] = {
    "resume_from": "Core resume control for START/HITL continuation; removing breaks restart flow.",
    "state_version": "Migration safety gate for persisted runs; required for version-aware execution.",
    "workflow_thread_id": "Failure-recovery execution context identifier for retried runs.",
    "thread_reset_done": "Failure/timeout reset marker paired with workflow_thread_id lifecycle.",
    "pending_db_commit": "Transactional commit envelope for idempotent state replay.",
    "commit_executed": "Commit idempotency marker to prevent duplicate side effects.",
    "anchor_route": "Graph conditional routing key after anchor_resolve.",
    "graph_rag_route": "Graph conditional routing key after graph_rag.",
    "language_gate_route": "Graph conditional routing key after output_language_gate.",
}


class AgentWorkflowState(TypedDict):
    story_id: str
    chapter_id: int
    pov_character_id: str
    active_epoch_id: str
    narrative_directive: str
    tone_direction: str
    target_word_count: int
    bible_context: str
    graph_context: str
    vector_context: str
    chunk_context: NotRequired[str]
    local_enforced_rules_context: NotRequired[str]
    previous_chapter_summary: str
    previous_chapter_tail_excerpt: NotRequired[str]
    recent_chapter_context: str
    continuity_notes: list[str]
    author_safe_continuity_notes: list[str]
    recent_entity_names: list[str]
    ground_truth_events: list[dict[str, Any]]
    narrative_script: str
    chapter_start_location: str
    author_goal: str
    must_include_beats: list[str]
    must_include_beat_outlines: NotRequired[list[dict[str, Any]]]
    reader_visible_facts: list[str]
    reader_unresolved_questions: list[str]
    private_facts_or_secret_actions: list[str]
    ending_state_shift: str
    chapter_end_location_hint: str
    ending_boundary_rule: str
    forbidden_next_scene_actions: list[str]
    forbidden_reveals: list[str]
    last_known_location: str
    plan_retry_limit: int
    plan_feedback: list[dict[str, Any]]
    plan_retry_count: int
    anchor_achieved: bool
    current_draft: str
    draft_loop_retry_limit: int
    draft_loop_retry_count: int
    draft_retry_count: int
    draft_feedback: list[dict[str, Any]]
    length_adjustment: LengthAdjustment | str
    reader_feedback: list[dict[str, Any]]
    reader_retry_count: int
    best_draft_score: int
    best_draft_content: str
    requires_hitl: bool
    hitl_reason: str
    hitl_decision_mode: HitlDecisionMode | str
    workflow_status: WorkflowStatus | str
    last_reader_score: int
    last_agent: str
    trace_id: str
    pending_hitl_options: list[dict[str, Any]]
    plan_route: NotRequired[str]
    draft_route: NotRequired[str]
    reader_route: NotRequired[str]
    resume_from: NotRequired[str]
    state_updater_output: NotRequired[dict[str, Any]]
    state_transaction_id: NotRequired[str]
    author_extraction_surface_hints: NotRequired[list[dict[str, Any]]]
    chapter_type: NotRequired[ChapterType | str]
    selected_anchor_ids: NotRequired[list[str]]
    next_anchor_ids: NotRequired[list[str]]
    b_story_directive: NotRequired[str | None]
    b_story_type: NotRequired[BStoryType | str | None]
    new_elements_to_introduce: NotRequired[list[dict[str, Any]]]
    request_new_b_story: NotRequired[dict[str, Any] | None]
    recent_b_story_types: NotRequired[list[str]]
    planned_graph_nodes: NotRequired[list[dict[str, Any]]]
    normalized_length_min: NotRequired[int]
    normalized_length_max: NotRequired[int]
    plan_warnings: NotRequired[list[str]]
    pending_chapter_extraction: NotRequired[dict[str, Any]]
    # Chunking / retrieval alignment (generated before extraction).
    # Each entry is JSON-serializable with keys like:
    # chunk_id, chunk_index, chapter_id, source_chapter_id, source_role, text_chunk
    chapter_chunks: NotRequired[list[dict[str, Any]]]
    b_story_resolution: NotRequired[dict[str, Any]]
    pending_cast_updates: NotRequired[list[dict[str, Any]]]
    pending_cast_evolutions: NotRequired[list[dict[str, Any]]]
    extraction_gate_failure_streak: NotRequired[int]
    last_chapter_extraction_metrics: NotRequired[dict[str, Any]]
    extraction_hitl_limit: NotRequired[int]
    manual_entity_remap: NotRequired[list[dict[str, Any]]]
    mandatory_extraction_skips: NotRequired[list[str]]
    manual_plan_force_approve: NotRequired[bool]
    graph_rag_context_tier: NotRequired[int]
    hitl_extraction_remap_hints: NotRequired[list[dict[str, Any]]]
    b_story_resolution_hitl_candidate: NotRequired[dict[str, Any]]
    anchor_resolution: NotRequired[dict[str, Any]]
    anchor_resolution_hitl_candidate: NotRequired[dict[str, Any]]
    anchor_route: NotRequired[str]
    resolved_anchors: NotRequired[list[str]]
    active_anchors: NotRequired[list[str]]
    anchor_candidates: NotRequired[list[str]]
    storyline_metadata: NotRequired[list[dict[str, Any]]]
    anchor_nodes: NotRequired[list[dict[str, Any]]]
    context_overflow_char_estimate: NotRequired[int]
    cast_slim_view: NotRequired[list[dict[str, Any]]]
    cast_full_view: NotRequired[list[dict[str, Any]]]
    all_milestone_summaries: NotRequired[list[dict[str, Any]]]
    recent_chapter_summaries: NotRequired[list[dict[str, Any]]]
    global_conflict_type_top3: NotRequired[list[dict[str, Any]]]
    global_resolution_method_top3: NotRequired[list[dict[str, Any]]]
    lore_mysteries_progression: NotRequired[list[dict[str, Any]]]
    resolution_cooldown_constraint: NotRequired[dict[str, Any]]
    ending_vibe_cooldown_constraint: NotRequired[dict[str, Any]]
    general_world_lore: NotRequired[str]
    author_chapter_plan: NotRequired[str]
    chapter_outline: NotRequired[str]
    chapter_hard_rules: NotRequired[str]
    safe_chapter_rules: NotRequired[str]
    alignment_log: NotRequired[str]
    alignment_hitl_retry_count: NotRequired[int]
    original_draft_narrative_script: NotRequired[str]
    original_draft_must_include_beats: NotRequired[list[str]]
    original_draft_ground_truth_events: NotRequired[list[dict[str, Any]]]
    allowed_identity_reveals_this_chapter: NotRequired[list[str]]
    ai_freedom_level: NotRequired[AiFreedomLevel | str]
    outline_binding_mode: NotRequired[str]
    director_state_brief: NotRequired[str]
    human_outline_conflict_notes: NotRequired[list[str]]
    this_chapter_pacing_limit: NotRequired[str]
    language_gate_route: NotRequired[str]
    output_language_hitl_waived: NotRequired[bool]
    hitl_output_language_detail: NotRequired[str]
    hitl_expected_output_language: NotRequired[str]
    story_output_language: NotRequired[str]
    pending_db_commit: NotRequired[dict[str, Any]]
    commit_executed: NotRequired[bool]
    failure_type: NotRequired[str]
    timeout_bucket: NotRequired[str]
    workflow_thread_id: NotRequired[str]
    thread_reset_done: NotRequired[bool]
    state_version: NotRequired[int]
    graph_rag_route: NotRequired[str]
    anchor_hitl_required: NotRequired[bool]
    volume_stretch_required: NotRequired[bool]
    volume_stretch_applied_to_chapter: NotRequired[int]
    word_count: NotRequired[int]
    require_chapter_review: NotRequired[bool]


class SafeAuthorPayload(BaseModel):
    narrative_script: str
    chapter_start_location: str = ""
    author_goal: str = ""
    must_include_beats: list[str] = Field(default_factory=list)
    must_include_beat_outlines: list[BeatOutline] = Field(default_factory=list)
    reader_visible_facts: list[str] = Field(default_factory=list)
    reader_unresolved_questions: list[str] = Field(default_factory=list)
    chapter_end_location_hint: str = ""
    ending_state_shift: str = ""
    ending_boundary_rule: str = ""
    forbidden_next_scene_actions: list[str] = Field(default_factory=list)
    forbidden_reveals: list[str] = Field(default_factory=list)
    tone_direction: str
    target_word_count: int
    normalized_length_min: int = 0
    normalized_length_max: int = 0
    previous_chapter_summary: str = ""
    previous_chapter_tail_excerpt: str = ""
    previous_attempt_draft: str = ""
    last_known_location: str = ""
    local_enforced_rules_context: str = ""
    author_safe_continuity_notes: list[str] = Field(default_factory=list)
    recent_entity_names: list[str] = Field(default_factory=list)
    active_character_profiles: list[dict[str, str]] = Field(default_factory=list)
    draft_feedback: list[dict[str, Any]] = Field(default_factory=list)
    reader_feedback: list[dict[str, Any]] = Field(default_factory=list)
    length_adjustment: LengthAdjustment = LengthAdjustment.NONE
    mandatory_new_entities: list[MandatoryNewEntity] = Field(default_factory=list)
    general_world_lore: str = ""
    safe_chapter_rules: str = ""
    ai_freedom_level: str = "balanced"
    outline_binding_mode: str = "ABSENT"


class SafePlannerPayload(BaseModel):
    active_epoch_id: str
    pov_character_id: str
    narrative_directive: str
    story_premise: str = ""
    current_volume_title: str = ""
    current_volume_summary: str = ""
    current_anchor_title: str = ""
    current_anchor_description: str = ""
    ready_anchor_candidates: list[dict[str, Any]] = Field(default_factory=list)
    blocked_anchor_candidates: list[dict[str, Any]] = Field(default_factory=list)
    graph_context: str
    vector_context: str
    bible_context: str
    local_enforced_rules_context: str = ""
    previous_chapter_summary: str = ""
    previous_chapter_tail_excerpt: str = ""
    recent_chapter_context: str = ""
    last_known_location: str = ""
    previous_attempt_ground_truth_events: list[EventOutline] = Field(default_factory=list)
    previous_attempt_narrative_script: str = ""
    continuity_notes: list[str] = Field(default_factory=list)
    recent_entity_names: list[str] = Field(default_factory=list)
    prior_feedback: list[dict[str, Any]] = Field(default_factory=list)
    default_chapter_words: int = Field(
        default=2500,
        description="建議字數起點（來自 state／設定），Planner 可依本章內容調整，非卷攤分。",
    )
    chapter_word_min: int = 800
    chapter_word_max: int = 12000
    chapter_type: str = "PLOT_DRIVEN"
    selected_anchor_ids: list[str] = Field(default_factory=list)
    next_anchor_ids: list[str] = Field(default_factory=list)
    b_story_directive: str | None = None
    new_elements_to_introduce: list[dict[str, Any]] = Field(default_factory=list)
    request_new_b_story: dict[str, Any] | None = None
    lore_mysteries_progression: list[dict[str, Any]] = Field(default_factory=list)
    ending_vibe_cooldown_constraint: dict[str, Any] = Field(default_factory=dict)
    general_world_lore: str = ""
    author_chapter_plan: str = ""
    ai_freedom_level: str = "balanced"
    outline_binding_mode: str = "ABSENT"
    director_state_brief: str = ""
    this_chapter_pacing_limit: str = ""


class SafeSupervisorPayload(BaseModel):
    chapter_id: int
    current_chapter_id: int
    active_epoch_id: str
    selected_anchor_ids: list[str] = Field(default_factory=list)
    next_anchor_ids: list[str] = Field(default_factory=list)
    ready_anchor_candidates: list[dict[str, Any]] = Field(default_factory=list)
    blocked_anchor_candidates: list[dict[str, Any]] = Field(default_factory=list)
    target_word_count: int = 0
    chapter_word_min: int = 800
    chapter_word_max: int = 12000
    words_per_beat_floor: int = 200
    normalized_current_draft_length: int = 0
    previous_chapter_summary: str = ""
    previous_chapter_tail_excerpt: str = ""
    recent_chapter_context: str = ""
    last_known_location: str = ""
    ground_truth_events: list[EventOutline] = Field(default_factory=list)
    narrative_script: str = ""
    chapter_start_location: str = ""
    chapter_end_location_hint: str = ""
    ending_boundary_rule: str = ""
    forbidden_next_scene_actions: list[str] = Field(default_factory=list)
    must_include_beats: list[str] = Field(default_factory=list)
    must_include_beat_outlines: list[BeatOutline] = Field(default_factory=list)
    current_draft: str = ""
    graph_context: str = ""
    vector_context: str = ""
    bible_context: str = ""
    chapter_type: str = "PLOT_DRIVEN"
    b_story_directive: str | None = None
    new_elements_to_introduce: list[dict[str, Any]] = Field(default_factory=list)
    proposed_new_nodes: list[dict[str, Any]] = Field(default_factory=list)
    request_new_b_story: dict[str, Any] | None = None
    normalized_length_min: int = 0
    normalized_length_max: int = 0
    mandatory_new_entities: list[MandatoryNewEntity] = Field(default_factory=list)
    lore_mysteries_progression: list[dict[str, Any]] = Field(default_factory=list)
    resolution_cooldown_constraint: dict[str, Any] = Field(default_factory=dict)
    ending_vibe_cooldown_constraint: dict[str, Any] = Field(default_factory=dict)
    allowed_identity_reveals_this_chapter: list[str] = Field(default_factory=list)
    chapter_outline: str = ""
    ai_freedom_level: str = "balanced"
    outline_binding_mode: str = "ABSENT"


class WorkflowBootstrapState(BaseModel):
    story_id: str
    chapter_id: int
    trace_id: str


def build_initial_state(
    story_id: str,
    chapter_id: int,
    trace_id_or_legacy_unachieved: str | list[dict[str, Any]] | None = None,
    trace_id: str | None = None,
    *,
    plan_retry_limit: int = 3,
    draft_loop_retry_limit: int = 3,
    pov_character_id: str = "char_public_observer",
    author_chapter_plan: str = "",
    chapter_outline: str = "",
    chapter_hard_rules: str = "",
    ai_freedom_level: str = "balanced",
    outline_binding_mode: str = "ABSENT",
) -> AgentWorkflowState:
    # Backward compatibility for older callers:
    # build_initial_state(story_id, chapter_id, unachieved_anchors, trace_id, ...)
    if trace_id is None:
        resolved_trace_id = str(trace_id_or_legacy_unachieved or "")
    else:
        resolved_trace_id = str(trace_id)
    return AgentWorkflowState(
        story_id=story_id,
        chapter_id=chapter_id,
        pov_character_id=pov_character_id,
        active_epoch_id="epoch_present",
        narrative_directive="推進劇情",
        tone_direction="懸疑",
        target_word_count=2500,
        bible_context="",
        graph_context="",
        vector_context="",
        previous_chapter_summary="",
        previous_chapter_tail_excerpt="",
        recent_chapter_context="",
        continuity_notes=[],
        author_safe_continuity_notes=[],
        recent_entity_names=[],
        ground_truth_events=[],
        narrative_script="",
        chapter_start_location="",
        author_goal="",
        must_include_beats=[],
        reader_visible_facts=[],
        reader_unresolved_questions=[],
        private_facts_or_secret_actions=[],
        ending_state_shift="",
        chapter_end_location_hint="",
        ending_boundary_rule="",
        forbidden_next_scene_actions=[],
        forbidden_reveals=[],
        last_known_location="",
        plan_retry_limit=plan_retry_limit,
        plan_feedback=[],
        plan_retry_count=0,
        anchor_achieved=False,
        current_draft="",
        draft_loop_retry_limit=draft_loop_retry_limit,
        draft_loop_retry_count=0,
        draft_retry_count=0,
        draft_feedback=[],
        length_adjustment=LengthAdjustment.NONE,
        reader_feedback=[],
        reader_retry_count=0,
        best_draft_score=0,
        best_draft_content="",
        requires_hitl=False,
        hitl_reason="",
        hitl_decision_mode=HitlDecisionMode.NONE.value,
        workflow_status="RUNNING",
        last_reader_score=0,
        last_agent="bootstrap",
        trace_id=resolved_trace_id,
        pending_hitl_options=[],
        plan_route="planner",
        draft_route="author",
        reader_route="author",
        resume_from="director",
        chapter_type="PLOT_DRIVEN",
        selected_anchor_ids=[],
        next_anchor_ids=[],
        b_story_directive=None,
        b_story_type=None,
        new_elements_to_introduce=[],
        request_new_b_story=None,
        recent_b_story_types=[],
        planned_graph_nodes=[],
        normalized_length_min=0,
        normalized_length_max=0,
        plan_warnings=[],
        author_extraction_surface_hints=[],
        extraction_gate_failure_streak=0,
        last_chapter_extraction_metrics={},
        extraction_hitl_limit=4,
        manual_entity_remap=[],
        mandatory_extraction_skips=[],
        manual_plan_force_approve=False,
        graph_rag_context_tier=2,
        hitl_extraction_remap_hints=[],
        anchor_route="profile_expander",
        anchor_resolution={},
        anchor_resolution_hitl_candidate={},
        resolved_anchors=[],
        active_anchors=[],
        anchor_candidates=[],
        storyline_metadata=[],
        anchor_nodes=[],
        pending_cast_updates=[],
        pending_cast_evolutions=[],
        context_overflow_char_estimate=0,
        all_milestone_summaries=[],
        recent_chapter_summaries=[],
        global_conflict_type_top3=[],
        global_resolution_method_top3=[],
        lore_mysteries_progression=[],
        resolution_cooldown_constraint={},
        ending_vibe_cooldown_constraint={},
        general_world_lore="",
        author_chapter_plan=author_chapter_plan or "",
        chapter_outline=chapter_outline or "",
        chapter_hard_rules=chapter_hard_rules or "",
        safe_chapter_rules="",
        alignment_log="",
        alignment_hitl_retry_count=0,
        original_draft_narrative_script="",
        original_draft_must_include_beats=[],
        original_draft_ground_truth_events=[],
        allowed_identity_reveals_this_chapter=[],
        ai_freedom_level=ai_freedom_level,
        outline_binding_mode=outline_binding_mode,
        director_state_brief="",
        human_outline_conflict_notes=[],
        this_chapter_pacing_limit="",
        pending_db_commit={},
        commit_executed=False,
        failure_type="",
        timeout_bucket="",
        workflow_thread_id=resolved_trace_id,
        thread_reset_done=False,
        state_version=2,
    )


def normalize_workflow_state(state: dict[str, Any]) -> dict[str, Any]:
    """Fill defaults for workflow state (migration / resume compatibility)."""
    defaults: dict[str, Any] = {
        "chapter_type": ChapterType.PLOT_DRIVEN.value,
        "selected_anchor_ids": [],
        "next_anchor_ids": [],
        "b_story_directive": None,
        "b_story_type": None,
        "new_elements_to_introduce": [],
        "request_new_b_story": None,
        "recent_b_story_types": [],
        "planned_graph_nodes": [],
        "normalized_length_min": 0,
        "normalized_length_max": 0,
        "plan_warnings": [],
        "pending_cast_updates": [],
        "pending_cast_evolutions": [],
        "previous_chapter_tail_excerpt": "",
        "author_extraction_surface_hints": [],
        "extraction_gate_failure_streak": 0,
        "last_chapter_extraction_metrics": {},
        "extraction_hitl_limit": 4,
        "manual_entity_remap": [],
        "mandatory_extraction_skips": [],
        "manual_plan_force_approve": False,
        "graph_rag_context_tier": 2,
        "hitl_extraction_remap_hints": [],
        "anchor_route": "profile_expander",
        "anchor_resolution": {},
        "anchor_resolution_hitl_candidate": {},
        "resolved_anchors": [],
        "active_anchors": [],
        "anchor_candidates": [],
        "storyline_metadata": [],
        "anchor_nodes": [],
        "context_overflow_char_estimate": 0,
        "all_milestone_summaries": [],
        "recent_chapter_summaries": [],
        "global_conflict_type_top3": [],
        "global_resolution_method_top3": [],
        "lore_mysteries_progression": [],
        "resolution_cooldown_constraint": {},
        "ending_vibe_cooldown_constraint": {},
        "general_world_lore": "",
        "author_chapter_plan": "",
        "chapter_outline": "",
        "chapter_hard_rules": "",
        "safe_chapter_rules": "",
        "alignment_log": "",
        "alignment_hitl_retry_count": 0,
        "allowed_identity_reveals_this_chapter": [],
        "local_enforced_rules_context": "",
        "ai_freedom_level": "balanced",
        "outline_binding_mode": "ABSENT",
        "director_state_brief": "",
        "human_outline_conflict_notes": [],
        "this_chapter_pacing_limit": "",
        "language_gate_route": "",
        "output_language_hitl_waived": False,
        "hitl_output_language_detail": "",
        "hitl_expected_output_language": "",
        "story_output_language": "zh-Hant",
        "pending_db_commit": {},
        "commit_executed": False,
        "failure_type": "",
        "timeout_bucket": "",
        "workflow_thread_id": "",
        "thread_reset_done": False,
        "state_version": 2,
        "graph_rag_route": "planner",
        "anchor_hitl_required": False,
        "volume_stretch_required": False,
        "word_count": 0,
        "require_chapter_review": False,
    }
    for key, val in defaults.items():
        if key not in state:
            state[key] = val
    neo = state.get("new_elements_to_introduce")
    if neo and isinstance(neo, list) and neo and isinstance(neo[0], str):
        state["new_elements_to_introduce"] = [
            {"need": str(s).strip(), "reason": ""} for s in neo if str(s).strip()
        ]
    if state.get("resume_from") == "prose_polish":
        state["resume_from"] = "extraction_gate"
    canonicalize_workflow_state_contract(state)
    return state


def canonicalize_workflow_state_contract(state: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy aliases to canonical state keys without removing old keys."""
    # Canonical outline field: chapter_outline; keep legacy author_chapter_plan mirrored.
    outline = str(state.get("chapter_outline") or state.get("author_chapter_plan") or "").strip()
    state["chapter_outline"] = outline
    state["author_chapter_plan"] = outline

    # Canonical anchor target field: selected_anchor_ids.
    selected = [str(x).strip() for x in (state.get("selected_anchor_ids") or []) if str(x).strip()]
    state["selected_anchor_ids"] = selected

    # Clean removed legacy keys when loading old runs.
    state.pop("post_polish_route", None)
    state.pop("manual_override_payload", None)
    state.pop("b_story_route", None)
    return state


def apply_length_bounds_to_state(state: dict[str, Any]) -> dict[str, Any]:
    """SSOT: derive normalized length window from target_word_count (single writer)."""
    from app.core.config import get_settings
    from app.services.workflow.output_language import default_chapter_target_words, normalize_output_language

    tw = int(state.get("target_word_count") or 0)
    if tw < 1:
        raw = str(state.get("story_output_language") or "").strip()
        if raw:
            tw = default_chapter_target_words(normalize_output_language(raw))
        else:
            tw = int(get_settings().default_chapter_words)
    state["target_word_count"] = tw
    state["normalized_length_min"] = int(tw * 0.65)
    state["normalized_length_max"] = int(tw * 1.35)
    return state


def planned_nodes_to_mandatory_entities(planned: list[dict[str, Any]]) -> list[MandatoryNewEntity]:
    out: list[MandatoryNewEntity] = []
    for row in planned:
        if not row.get("mandatory", True):
            continue
        if row.get("node_type") not in ("CHARACTER", "PERSONA", "LOCATION", "ITEM"):
            continue
        node_id = (row.get("node_id") or "").strip()
        if not node_id:
            continue
        role = (row.get("role") or "").strip()
        canonical = (row.get("canonical_name") or "").strip()
        brief = (row.get("writing_brief") or "").strip()
        kws = [x for x in [role, canonical] if x]
        out.append(
            MandatoryNewEntity(
                node_id=node_id,
                role=role,
                canonical_name=canonical,
                writing_brief=brief or f"本章必須讓讀者能辨識此實體（{role or canonical or node_id}）。",
                search_keywords=kws,
            )
        )
    return out
