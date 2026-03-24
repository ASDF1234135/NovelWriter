from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional, Union

MacroCastRole = Literal["protagonist", "supporting"]

from pydantic import BaseModel, Field


class NodeType(str, Enum):
    CHARACTER = "CHARACTER"
    PERSONA = "PERSONA"
    LOCATION = "LOCATION"
    ITEM = "ITEM"
    CONCEPT = "CONCEPT"
    EPOCH = "EPOCH"
    EVENT = "EVENT"


class EdgeType(str, Enum):
    LOCATED_IN = "LOCATED_IN"
    HAS_ITEM = "HAS_ITEM"
    HAS_RELATION = "HAS_RELATION"
    PARTICIPATED_IN = "PARTICIPATED_IN"
    IS_ACTUALLY = "IS_ACTUALLY"
    HAS_ATTRIBUTE = "HAS_ATTRIBUTE"
    BELIEVED_AS = "BELIEVED_AS"
    KNOWS_ABOUT = "KNOWS_ABOUT"
    BELONGS_TO_EPOCH = "BELONGS_TO_EPOCH"
    HAPPENED_BEFORE = "HAPPENED_BEFORE"
    CAUSED = "CAUSED"


class BaseNode(BaseModel):
    node_id: str = Field(..., description="Global unique node ID, such as char_001.")
    node_type: NodeType
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)


class CharacterNode(BaseNode):
    node_type: Literal[NodeType.CHARACTER] = NodeType.CHARACTER
    is_alive: bool = True
    description: str


class PersonaNode(BaseNode):
    node_type: Literal[NodeType.PERSONA] = NodeType.PERSONA
    is_alive: bool = True
    description: str = Field(..., description="Visible appearance and behavioral traits.")


class EpochNode(BaseNode):
    node_type: Literal[NodeType.EPOCH] = NodeType.EPOCH
    order_index: int


class LocationNode(BaseNode):
    node_type: Literal[NodeType.LOCATION] = NodeType.LOCATION
    environmental_condition: str = "正常"
    is_accessible: bool = True


class ItemNode(BaseNode):
    node_type: Literal[NodeType.ITEM] = NodeType.ITEM
    item_status: str = "完好"
    is_unique: bool = False


class EventNode(BaseNode):
    node_type: Literal[NodeType.EVENT] = NodeType.EVENT


class ConceptNode(BaseNode):
    node_type: Literal[NodeType.CONCEPT] = NodeType.CONCEPT


GraphNode = Union[
    CharacterNode,
    PersonaNode,
    EpochNode,
    LocationNode,
    ItemNode,
    EventNode,
    ConceptNode,
]


class GraphEdge(BaseModel):
    edge_id: str
    source_id: str
    relation_type: EdgeType
    target_id: str
    valid_epoch: str
    start_event_id: str
    end_event_id: Optional[str] = None
    is_truth: bool
    is_public: bool = False
    known_by: list[str] = Field(default_factory=list)
    holder: list[str] = Field(default_factory=list)
    context_details: str = ""


class StoryInput(BaseModel):
    title: str
    premise: str = Field(..., description="One-line story summary.")
    bible: dict[str, Any] = Field(default_factory=dict)
    target_total_words: int = 100_000
    plan_retry_limit: int = Field(default=3, ge=0, le=20)
    draft_loop_retry_limit: int = Field(default=3, ge=0, le=20)


class VolumePlan(BaseModel):
    volume_id: str
    title: str
    summary: str
    chapter_start: int
    chapter_end: int
    target_volume_words: int = 0


class MacroVolumeDraft(BaseModel):
    title: str
    summary: str
    chapter_start: int
    chapter_end: int
    target_volume_words: int = 0


class MacroNestedAnchorDraft(BaseModel):
    """Anchor nested under a volume in macro LLM output (no volume_index)."""

    title: str
    description: str
    target_state: dict[str, Any] = Field(default_factory=dict)
    chapter_target: int
    priority: int = 1


class MacroVolumePlanDraft(BaseModel):
    """One volume plus 3–5 anchors that must fall in this volume's chapter range."""

    title: str
    summary: str
    chapter_start: int
    chapter_end: int
    target_volume_words: int = 0
    anchors: list[MacroNestedAnchorDraft] = Field(default_factory=list)


class MacroCastMember(BaseModel):
    """LLM output: cast roster (no node_id; assigned at normalize)."""

    canonical_name: str
    role: MacroCastRole = "supporting"
    short_bio: str = ""
    aliases: list[str] = Field(default_factory=list)


class StoryCastMemberStored(BaseModel):
    """Persisted cast row + graph node id after macro compile."""

    node_id: str
    canonical_name: str
    role: MacroCastRole
    short_bio: str = ""
    aliases: list[str] = Field(default_factory=list)


class StateAnchor(BaseModel):
    anchor_id: str
    story_id: str
    volume_id: str
    title: str
    description: str
    target_state: dict[str, Any]
    chapter_target: int
    priority: int = 1


class MacroAnchorDraft(BaseModel):
    """Legacy flat macro anchor; prefer nested anchors under MacroVolumePlanDraft."""

    title: str
    description: str
    target_state: dict[str, Any] = Field(default_factory=dict)
    chapter_target: int
    volume_index: int = 1
    priority: int = 1


class MacroPlanOutput(BaseModel):
    total_chapters: int = 12
    volumes: list[MacroVolumePlanDraft] = Field(default_factory=list)
    cast: list[MacroCastMember] = Field(default_factory=list)
    initial_b_stories: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Optional seed subplots as {id, desc} dicts merged into bible_json.active_b_stories at macro compile.",
    )


class ChapterType(str, Enum):
    PLOT_DRIVEN = "PLOT_DRIVEN"
    CHARACTER_DRIVEN = "CHARACTER_DRIVEN"
    WORLD_BUILDING = "WORLD_BUILDING"


class DirectorOutput(BaseModel):
    chapter_id: int
    active_epoch_id: str
    pov_character_id: str
    narrative_directive: str
    tone_direction: str
    target_anchor_id: Optional[str] = None
    chapter_type: ChapterType = ChapterType.PLOT_DRIVEN
    b_story_directive: Optional[str] = None
    new_elements_to_introduce: list[str] = Field(default_factory=list)


class EventOutline(BaseModel):
    event_id: str
    description: str
    caused_by_event_id: Optional[str] = None


class ProposedGraphNode(BaseModel):
    """Planner-invented graph node for genesis; max 3 per chapter (enforced in planner_node)."""

    node_id: str
    node_type: NodeType
    role: str = ""
    canonical_name: str = ""
    writing_brief: str = ""
    mandatory: bool = True


class MandatoryNewEntity(BaseModel):
    """Fed to Author / Draft supervisor for required on-screen presence."""

    node_id: str
    role: str = ""
    canonical_name: str = ""
    writing_brief: str = ""
    search_keywords: list[str] = Field(default_factory=list)


class BStorySeed(BaseModel):
    """New subplot thread to merge into bible active_b_stories on successful chapter commit."""

    id: str = Field(..., min_length=1, max_length=80)
    desc: str = Field(default="", max_length=800)


class PlannerOutput(BaseModel):
    ground_truth_events: list[EventOutline]
    narrative_script: str
    target_word_count: int = Field(..., ge=1, description="本章目標字數（正規化計數語意與 draft 審核一致）。")
    chapter_start_location: str = ""
    author_goal: str = ""
    must_include_beats: list[str] = Field(default_factory=list)
    reader_visible_facts: list[str] = Field(default_factory=list)
    reader_unresolved_questions: list[str] = Field(default_factory=list)
    private_facts_or_secret_actions: list[str] = Field(default_factory=list)
    ending_state_shift: str = ""
    chapter_end_location_hint: str = ""
    ending_boundary_rule: str = ""
    forbidden_next_scene_actions: list[str] = Field(default_factory=list)
    forbidden_reveals: list[str] = Field(default_factory=list)
    author_safe_continuity_notes: list[str] = Field(
        default_factory=list,
        description=(
            "0-4 條給主筆 author 的連續性提醒；須經 POV／出場過濾，"
            "不得直接複製 RAG 未解線索裡尚未被讀者或 POV 角色正當得知的專名與劇情。"
        ),
    )
    proposed_new_nodes: list[ProposedGraphNode] = Field(default_factory=list)
    new_active_b_stories: list[BStorySeed] = Field(
        default_factory=list,
        description="本章若開啟全新副線（有獨立 id），最多 2 條；成功定稿後併入 bible。",
    )


class ViolationType(str, Enum):
    NONE = "NONE"
    PHYSICAL_CONFLICT = "PHYSICAL_CONFLICT"
    ANCHOR_DIVERGENCE = "ANCHOR_DIVERGENCE"
    POV_LEAK = "POV_LEAK"
    INCONSISTENCY = "INCONSISTENCY"
    WORD_COUNT_UNMATCH = "WORD_COUNT_UNMATCH"
    MISSING_DIRECTIVE = "MISSING_DIRECTIVE"
    MISSING_MANDATORY_ENTITY_MAPPING = "MISSING_MANDATORY_ENTITY_MAPPING"


class SuggestionType(str, Enum):
    NONE = "NONE"
    MODIFY = "MODIFY"
    REWRITE = "REWRITE"


class LengthAdjustment(str, Enum):
    NONE = "NONE"
    EXPAND = "EXPAND"
    COMPRESS = "COMPRESS"


class PlanSupervisorOutput(BaseModel):
    is_approved: bool
    violation_type: list[ViolationType] = Field(default_factory=lambda: [ViolationType.NONE])
    suggestion_type: SuggestionType = SuggestionType.NONE
    feedback_to_agent: str = ""
    anchor_achieved: bool = False
    soft_warnings: list[str] = Field(default_factory=list)


class BStoryResolutionOutput(BaseModel):
    """Post-extraction subplot closure; evidence ids must be substantiated in structured extraction (R2c)."""

    resolution_analysis: str = Field(
        ...,
        min_length=20,
        description="Chain-of-thought: why each listed subplot is fully and irreversibly resolved, or why none are.",
    )
    resolution_evidence_event_ids: list[str] = Field(default_factory=list)
    resolved_b_stories: list[str] = Field(default_factory=list)


class DraftSupervisorOutput(BaseModel):
    is_approved: bool
    violation_type: list[ViolationType] = Field(default_factory=lambda: [ViolationType.NONE])
    suggestion_type: SuggestionType = SuggestionType.NONE
    feedback_to_agent: str = ""
    length_adjustment: LengthAdjustment = LengthAdjustment.NONE


class AuthorExtractionSurfaceEntry(BaseModel):
    """Per-node surface strings that appear verbatim in chapter text (validated server-side)."""

    node_id: str = Field(..., min_length=1)
    surface_forms: list[str] = Field(default_factory=list)


class AuthorExtractionHintsOutput(BaseModel):
    entries: list[AuthorExtractionSurfaceEntry] = Field(default_factory=list)


class AuthorOutput(BaseModel):
    chapter_content: str
    word_count: int
    extraction_surface_hints: list[AuthorExtractionSurfaceEntry] = Field(default_factory=list)


class ReaderOutput(BaseModel):
    is_approved: bool
    literary_score: int = Field(..., ge=0, le=100)
    suggestion_type: SuggestionType = SuggestionType.NONE
    critique: str


class ExtractedEntity(BaseModel):
    node_id: str = ""
    node_type: NodeType
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    summary: str = ""
    properties: dict[str, Any] = Field(default_factory=dict)


class ExtractedRelation(BaseModel):
    source_node_id: str = ""
    source_name: str = ""
    relation_type: EdgeType
    target_node_id: str = ""
    target_name: str = ""
    context_details: str = ""
    is_truth: bool = True
    is_public: bool = False


class ChapterMemory(BaseModel):
    summary: str = ""
    unresolved_threads: list[str] = Field(default_factory=list)
    notable_entities: list[str] = Field(default_factory=list)
    latest_location: str = ""


class ChapterExtractionOutput(BaseModel):
    entities: list[ExtractedEntity] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)
    chapter_memory: ChapterMemory = Field(default_factory=ChapterMemory)


class ExtractedEntityCandidate(BaseModel):
    """LLM entity step output; final node_id is assigned by canonicalization."""

    suggested_node_id: str = ""
    node_type: NodeType
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    summary: str = ""
    properties: dict[str, Any] = Field(default_factory=dict)


class EntityExtractionOutput(BaseModel):
    entities: list[ExtractedEntityCandidate] = Field(default_factory=list)


class ChapterMemoryExtractionOutput(BaseModel):
    summary: str = ""
    unresolved_threads: list[str] = Field(default_factory=list)
    notable_entities: list[str] = Field(default_factory=list)
    latest_location: str = ""


class RelationExtractionOutput(BaseModel):
    relations: list[ExtractedRelation] = Field(default_factory=list)


class NodeMutation(BaseModel):
    action: Literal["CREATE_NODE", "UPDATE_NODE"]
    node_id: str
    node_type: NodeType
    properties: dict[str, Any]


class EdgeMutation(BaseModel):
    action: Literal["CREATE_EDGE", "UPDATE_EDGE", "DELETE_EDGE"]
    edge_id: Optional[str] = None
    source_id: str
    relation_type: EdgeType
    target_id: str
    attributes: dict[str, Any]


class VectorDocument(BaseModel):
    text_chunk: str
    metadata: dict[str, Any]


class StateUpdaterOutput(BaseModel):
    mutations: list[Union[NodeMutation, EdgeMutation]]
    vector_documents: list[VectorDocument]


class HitlDecisionMode(str, Enum):
    NONE = "NONE"
    DASHBOARD = "DASHBOARD"
    MANUAL_EDIT = "MANUAL_EDIT"
    STATE_INJECTION = "STATE_INJECTION"


class WorkflowStatus(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    WAITING_HITL = "WAITING_HITL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class StateTransactionStatus(str, Enum):
    PENDING = "PENDING"
    GRAPH_APPLIED = "GRAPH_APPLIED"
    VECTOR_APPLIED = "VECTOR_APPLIED"
    SQLITE_APPLIED = "SQLITE_APPLIED"
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"


class WorkflowRun(BaseModel):
    run_id: str
    story_id: str
    chapter_id: int
    status: WorkflowStatus
    current_agent: Optional[str] = None
    requires_hitl: bool = False
    hitl_reason: str = ""
    hitl_decision_mode: HitlDecisionMode = HitlDecisionMode.NONE


class WorkflowStepLog(BaseModel):
    step_id: str
    run_id: str
    agent_name: str
    step_index: int
    status: str
    input_payload: dict[str, Any]
    output_payload: dict[str, Any]
    masked_payload: dict[str, Any] = Field(default_factory=dict)
    token_usage: int = 0
    latency_ms: int = 0
    route_decision: str = ""


class StateTransactionRecord(BaseModel):
    transaction_id: str
    run_id: str
    story_id: str
    chapter_id: int
    status: StateTransactionStatus
    graph_applied: bool = False
    vector_applied: bool = False
    sqlite_applied: bool = False
    payload: dict[str, Any]
    error_text: str = ""


class GraphSnapshot(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class GraphQueryRequest(BaseModel):
    story_id: str
    active_epoch_id: str
    pov_character_id: str
    narrative_directive: str
    max_tokens: int = 6000


class HitlDecisionRequest(BaseModel):
    option_id: str
    rationale: str = ""


class HitlOutlineEditRequest(BaseModel):
    ground_truth_events: list[EventOutline]
    narrative_script: Optional[str] = None
    reason: str = ""


class HitlStateInjectionRequest(BaseModel):
    mutations: list[Union[NodeMutation, EdgeMutation]]
    reason: str = ""


class HitlDraftEditRequest(BaseModel):
    """Human replaces draft while paused at HITL; workflow resumes for another quality pass."""

    chapter_content: str
    best_draft_content: str = ""
    resume_from: str = "reader"
    reason: str = ""
