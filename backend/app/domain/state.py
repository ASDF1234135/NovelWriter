from __future__ import annotations

from typing import Any, NotRequired, TypedDict

from pydantic import BaseModel, Field

from app.domain.schema import EventOutline, HitlDecisionMode, LengthAdjustment


class AgentWorkflowState(TypedDict):
    story_id: str
    chapter_id: int
    pov_character_id: str
    active_epoch_id: str
    narrative_directive: str
    tone_direction: str
    target_word_count: int
    unachieved_anchors: list[dict[str, Any]]
    target_anchor_id: str | None
    bible_context: str
    graph_context: str
    vector_context: str
    previous_chapter_summary: str
    recent_chapter_context: str
    continuity_notes: list[str]
    author_safe_continuity_notes: list[str]
    recent_entity_names: list[str]
    ground_truth_events: list[dict[str, Any]]
    narrative_script: str
    chapter_start_location: str
    author_goal: str
    must_include_beats: list[str]
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
    hitl_decision_mode: str
    workflow_status: str
    last_reader_score: int
    last_agent: str
    trace_id: str
    pending_hitl_options: list[dict[str, Any]]
    plan_route: NotRequired[str]
    draft_route: NotRequired[str]
    reader_route: NotRequired[str]
    resume_from: NotRequired[str]
    manual_override_payload: NotRequired[dict[str, Any]]
    state_updater_output: NotRequired[dict[str, Any]]
    state_transaction_id: NotRequired[str]


class SafeAuthorPayload(BaseModel):
    narrative_script: str
    chapter_start_location: str = ""
    author_goal: str = ""
    must_include_beats: list[str] = Field(default_factory=list)
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
    previous_attempt_draft: str = ""
    last_known_location: str = ""
    author_safe_continuity_notes: list[str] = Field(default_factory=list)
    recent_entity_names: list[str] = Field(default_factory=list)
    draft_feedback: list[dict[str, Any]] = Field(default_factory=list)
    reader_feedback: list[dict[str, Any]] = Field(default_factory=list)
    length_adjustment: LengthAdjustment = LengthAdjustment.NONE


class SafePlannerPayload(BaseModel):
    active_epoch_id: str
    pov_character_id: str
    narrative_directive: str
    target_anchor_id: str | None = None
    story_premise: str = ""
    current_volume_title: str = ""
    current_volume_summary: str = ""
    current_anchor_title: str = ""
    current_anchor_description: str = ""
    upcoming_unachieved_anchors: list[dict[str, Any]] = Field(default_factory=list)
    graph_context: str
    vector_context: str
    bible_context: str
    previous_chapter_summary: str = ""
    recent_chapter_context: str = ""
    last_known_location: str = ""
    previous_attempt_ground_truth_events: list[EventOutline] = Field(default_factory=list)
    previous_attempt_narrative_script: str = ""
    continuity_notes: list[str] = Field(default_factory=list)
    recent_entity_names: list[str] = Field(default_factory=list)
    prior_feedback: list[dict[str, Any]] = Field(default_factory=list)


class SafeSupervisorPayload(BaseModel):
    chapter_id: int
    current_chapter_id: int
    active_epoch_id: str
    target_anchor_id: str | None = None
    target_anchor_chapter: int | None = None
    chapters_until_anchor: int | None = None
    partial_convergence_allowed: bool = False
    target_word_count: int = 0
    normalized_current_draft_length: int = 0
    previous_chapter_summary: str = ""
    recent_chapter_context: str = ""
    last_known_location: str = ""
    ground_truth_events: list[EventOutline] = Field(default_factory=list)
    narrative_script: str = ""
    chapter_start_location: str = ""
    chapter_end_location_hint: str = ""
    ending_boundary_rule: str = ""
    forbidden_next_scene_actions: list[str] = Field(default_factory=list)
    must_include_beats: list[str] = Field(default_factory=list)
    current_draft: str = ""
    graph_context: str = ""
    vector_context: str = ""
    bible_context: str = ""


class WorkflowBootstrapState(BaseModel):
    story_id: str
    chapter_id: int
    unachieved_anchors: list[dict[str, Any]] = Field(default_factory=list)
    trace_id: str


def build_initial_state(
    story_id: str,
    chapter_id: int,
    unachieved_anchors: list[dict[str, Any]],
    trace_id: str,
    *,
    plan_retry_limit: int = 3,
    draft_loop_retry_limit: int = 3,
    pov_character_id: str = "char_public_observer",
) -> AgentWorkflowState:
    return AgentWorkflowState(
        story_id=story_id,
        chapter_id=chapter_id,
        pov_character_id=pov_character_id,
        active_epoch_id="epoch_present",
        narrative_directive="推進劇情",
        tone_direction="懸疑",
        target_word_count=2500,
        unachieved_anchors=unachieved_anchors,
        target_anchor_id=unachieved_anchors[0]["anchor_id"] if unachieved_anchors else None,
        bible_context="",
        graph_context="",
        vector_context="",
        previous_chapter_summary="",
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
        trace_id=trace_id,
        pending_hitl_options=[],
        plan_route="planner",
        draft_route="author",
        reader_route="author",
        resume_from="director",
    )
