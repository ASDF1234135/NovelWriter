from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional, Union

MacroCastRole = Literal["protagonist", "supporting", "antagonist"]

from pydantic import BaseModel, Field, field_validator


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


class StoryCastSeedEntry(BaseModel):
    """User-defined core cast roster hints for macro compile (optional)."""

    canonical_name: str
    role: MacroCastRole | None = Field(
        default=None,
        description="Optional role hint for the macro planner; normalize may still coerce duplicates.",
    )
    short_hint: str = Field(default="", description="One-line note for macro prompt context.")

    @field_validator("canonical_name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        s = (v or "").strip()
        if not s:
            raise ValueError("canonical_name must be non-empty")
        return s


class StoryInput(BaseModel):
    title: str
    premise: str = Field(..., description="One-line story summary.")
    bible: dict[str, Any] = Field(
        default_factory=dict,
        description="Deprecated for human entry; macro compile overwrites with generated bible. Omit or {}.",
    )
    macro_author_notes: str = Field(
        default="",
        description="Free-form author notes fed into macro compile (truncated server-side).",
    )
    cast_seed: list[StoryCastSeedEntry] = Field(
        default_factory=list,
        description="Optional structured core cast names for macro compile; empty keeps LLM-only roster.",
    )
    target_total_words: int = 100_000
    plan_retry_limit: int = Field(default=3, ge=0, le=20)
    draft_loop_retry_limit: int = Field(default=3, ge=0, le=20)


class StoryPatch(BaseModel):
    """Partial update allowed only before any workflow run (enforced in API/service)."""

    title: str | None = None
    premise: str | None = None
    target_total_words: int | None = Field(default=None, ge=1)
    plan_retry_limit: int | None = Field(default=None, ge=0, le=20)
    draft_loop_retry_limit: int | None = Field(default=None, ge=0, le=20)
    macro_author_notes: str | None = None
    cast_seed: list[StoryCastSeedEntry] | None = None


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
    # Selected keypoint IDs (e.g. ["KP1"]) referencing `macro_author_notes` for enforcement.
    notes_links: list[str] = Field(default_factory=list)


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
    age: str = Field(
        default="",
        description="Age or rough life-stage (e.g. 28 or 約三十).",
    )
    motivation: str = Field(default="", description="Core goals and drives (legacy; prefer core_motivation).")
    core_motivation: str = Field(default="", description="Primary drive across the series.")
    speech_style: str = Field(
        default="",
        description="Speech flavor; use sparingly in prose—not every line.",
    )
    fatal_flaw: str = Field(default="", description="Fatal flaw or main weakness.")
    quirks_and_habits: str = Field(default="", description="Observable habits or tics (use sparingly).")
    core_value: str = Field(default="", description="Core value / guiding principle (optional).")
    # Selected keypoint IDs (e.g. ["KP1"]) referencing `macro_author_notes` for enforcement.
    notes_links: list[str] = Field(default_factory=list)


class StoryCastMemberStored(BaseModel):
    """Persisted cast row + graph node id after macro compile."""

    node_id: str
    canonical_name: str
    role: MacroCastRole
    short_bio: str = ""
    aliases: list[str] = Field(default_factory=list)
    age: str = ""
    motivation: str = ""
    core_motivation: str = ""
    speech_style: str = ""
    fatal_flaw: str = ""
    quirks_and_habits: str = ""
    core_value: str = ""


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


class ChapterType(str, Enum):
    PLOT_DRIVEN = "PLOT_DRIVEN"
    CHARACTER_DRIVEN = "CHARACTER_DRIVEN"
    WORLD_BUILDING = "WORLD_BUILDING"


class ConflictType(str, Enum):
    MYSTERY = "MYSTERY"
    POLITICAL = "POLITICAL"
    SOCIAL = "SOCIAL"
    ROMANCE = "ROMANCE"
    SURVIVAL = "SURVIVAL"
    INVESTIGATION = "INVESTIGATION"
    HEIST = "HEIST"
    ESCAPE = "ESCAPE"
    PURSUIT = "PURSUIT"
    INTERNAL = "INTERNAL"
    MORAL_DILEMMA = "MORAL_DILEMMA"
    OTHER = "OTHER"


class ResolutionMethod(str, Enum):
    DISCOVERY = "DISCOVERY"
    NEGOTIATION = "NEGOTIATION"
    SACRIFICE = "SACRIFICE"
    DECEPTION = "DECEPTION"
    VIOLENCE = "VIOLENCE"
    ESCAPE = "ESCAPE"
    ALLIANCE = "ALLIANCE"
    TRADEOFF = "TRADEOFF"
    REVELATION = "REVELATION"
    FAILURE = "FAILURE"
    OTHER = "OTHER"


class EndingVibe(str, Enum):
    ACTION_CLIFFHANGER = "ACTION_CLIFFHANGER"
    SAFE_ROOM_EXPOSITION = "SAFE_ROOM_EXPOSITION"
    ON_THE_MOVE = "ON_THE_MOVE"
    DEVASTATING_LOSS = "DEVASTATING_LOSS"


class BStoryType(str, Enum):
    FETCH_QUEST = "FETCH_QUEST"
    RELATIONSHIP_DRAMA = "RELATIONSHIP_DRAMA"
    ENVIRONMENTAL_HAZARD = "ENVIRONMENTAL_HAZARD"
    LORE_DISCOVERY = "LORE_DISCOVERY"
    INTERNAL_CONFLICT = "INTERNAL_CONFLICT"
    UNKNOWN = "UNKNOWN"


class MacroInitialBStory(BaseModel):
    """Long-horizon subplot seeds at macro compile (merged into bible_json.active_b_stories)."""

    id: str = Field(..., min_length=1, max_length=80)
    desc: str = Field(default="", max_length=800)
    type: BStoryType = BStoryType.UNKNOWN
    resolution_condition: str = Field(
        default="",
        max_length=800,
        description="Objective completion criteria for downstream resolution checks.",
    )


class MacroPlanOutput(BaseModel):
    total_chapters: int = 12
    bible: dict[str, Any] = Field(
        default_factory=dict,
        description="Generated story bible (genre, tone, world_rules, factions, etc.).",
    )
    volumes: list[MacroVolumePlanDraft] = Field(default_factory=list)
    cast: list[MacroCastMember] = Field(default_factory=list)
    initial_b_stories: list[MacroInitialBStory] = Field(
        default_factory=list,
        description="Long-horizon b-story seeds merged into bible_json.active_b_stories at macro compile.",
    )


class DirectorNewElement(BaseModel):
    """Structured 'what to introduce this chapter' with rationale."""

    need: str = Field(default="", max_length=800)
    reason: str = Field(default="", max_length=1200)

    @field_validator("need", "reason", mode="before")
    @classmethod
    def _strip(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v


class DirectorNewBStoryRequest(BaseModel):
    """Director asks planner to open a new subplot with this typology."""

    type: BStoryType
    purpose: str = Field(default="", max_length=1200)


class DirectorOutput(BaseModel):
    chapter_id: int
    active_epoch_id: str
    pov_character_id: str
    narrative_directive: str
    tone_direction: str
    target_anchor_id: Optional[str] = None
    chapter_type: ChapterType = ChapterType.PLOT_DRIVEN
    b_story_directive: Optional[str] = None
    b_story_type: Optional[BStoryType] = None
    new_elements_to_introduce: list[DirectorNewElement] = Field(default_factory=list)
    request_new_b_story: Optional[DirectorNewBStoryRequest] = None

    @field_validator("new_elements_to_introduce", mode="before")
    @classmethod
    def _coerce_new_elements(cls, v: object) -> object:
        if v is None:
            return []
        if not isinstance(v, list):
            return v
        out: list[dict[str, str]] = []
        for item in v:
            if isinstance(item, str):
                t = item.strip()
                if t:
                    out.append({"need": t, "reason": ""})
            elif isinstance(item, dict):
                need = str(item.get("need") or item.get("label") or "").strip()
                reason = str(item.get("reason") or "").strip()
                if need or reason:
                    out.append({"need": need, "reason": reason})
        return out


class ChapterSummaryOutput(BaseModel):
    plot_summary: str = Field(..., min_length=30, max_length=520)
    conflict_type: ConflictType
    resolution_method: ResolutionMethod
    ending_vibe: EndingVibe = EndingVibe.ON_THE_MOVE


class MilestoneSummaryOutput(BaseModel):
    # Allow short fallback summaries (e.g. MockLLM / partial failures).
    milestone_summary: str = Field(..., min_length=20, max_length=900)


class EventOutline(BaseModel):
    event_id: str
    description: str
    caused_by_event_id: Optional[str] = None


class ProposedCharacterProfile(BaseModel):
    """High-level character sheet for planned CHARACTER nodes (aligns with macro cast fields)."""

    core_motivation: str = Field(default="", max_length=600)
    fatal_flaw: str = Field(default="", max_length=400)
    speech_style: str = Field(default="", max_length=240)
    quirks_and_habits: str = Field(default="", max_length=400)
    short_bio: str = Field(default="", max_length=500)
    age: str = Field(default="", max_length=48)
    core_value: str = Field(default="", max_length=600)


class ProposedGraphNode(BaseModel):
    """Planner-invented graph node for genesis; max 3 per chapter (enforced in planner_node)."""

    node_id: str
    node_type: NodeType
    role: str = ""
    canonical_name: str = ""
    writing_brief: str = ""
    mandatory: bool = True
    character_profile: Optional[ProposedCharacterProfile] = None


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
    type: BStoryType = BStoryType.UNKNOWN
    resolution_condition: str = Field(
        default="",
        max_length=800,
        description="Objective criteria for when this subplot is considered complete.",
    )


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
    ending_vibe: EndingVibe = EndingVibe.ON_THE_MOVE


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
    ending_vibe: EndingVibe = EndingVibe.ON_THE_MOVE


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
    context_hop_tier: int = Field(
        default=2,
        ge=0,
        le=2,
        description="0=minimal graph context, 2=full budget for query_context.",
    )


class HitlReason:
    """Stable string ids for workflow state hitl_reason (avoid magic strings scattered in code)."""

    PLAN_LOOP_EXCEEDED = "Plan_Loop_Exceeded"
    DRAFT_LOOP_EXCEEDED = "Draft_Loop_Exceeded"
    EXTRACTION_GATE_FAILED = "Extraction_Gate_Failed"
    B_STORY_RESOLUTION_FAILED = "B_Story_Resolution_Failed"
    B_STORY_COOLDOWN_VIOLATION = "B_Story_Cooldown_Violation"
    RESOLUTION_TACTIC_COOLDOWN_VIOLATION = "Resolution_Tactic_Cooldown_Violation"
    ENDING_VIBE_COOLDOWN_VIOLATION = "Ending_Vibe_Cooldown_Violation"
    CONTEXT_LENGTH_EXCEEDED = "Context_Length_Exceeded"


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
    merge_extraction_hints: bool = Field(
        default=False,
        description="If true, keep existing author_extraction_surface_hints instead of clearing them.",
    )


class HitlDirectorPatchRequest(BaseModel):
    """Human edits director-facing fields while paused (typically Plan_Loop_Exceeded)."""

    chapter_type: Optional[str] = None
    b_story_directive: Optional[str] = None
    b_story_type: Optional[str] = None
    new_elements_to_introduce: Optional[list[DirectorNewElement]] = None
    request_new_b_story: Optional[DirectorNewBStoryRequest] = None
    narrative_directive: Optional[str] = None
    reason: str = ""

    @field_validator("new_elements_to_introduce", mode="before")
    @classmethod
    def _coerce_hitl_new_elements(cls, v: object) -> object:
        if v is None:
            return v
        if not isinstance(v, list):
            return v
        out: list[dict[str, str]] = []
        for item in v:
            if isinstance(item, str):
                t = item.strip()
                if t:
                    out.append({"need": t, "reason": ""})
            elif isinstance(item, dict):
                need = str(item.get("need") or "").strip()
                reason = str(item.get("reason") or "").strip()
                if need or reason:
                    out.append({"need": need, "reason": reason})
        return out


class AuthorExtractionSurfaceHintEntry(BaseModel):
    node_id: str
    surface_forms: list[str] = Field(default_factory=list)


class HitlExtractionHintsRequest(BaseModel):
    """Merge surface hints for mandatory/planned entity alignment without rewriting the full draft."""

    entries: list[AuthorExtractionSurfaceHintEntry]
    resume_from: str = "draft_supervisor"
    waive_mandatory_node_ids: list[str] = Field(default_factory=list)
    reason: str = ""


class HitlEntityRemapEntry(BaseModel):
    """Map an extracted ghost node_id to a planned graph node_id."""

    from_node_id: str
    to_node_id: str


class HitlExtractionRemapRequest(BaseModel):
    entity_remaps: list[HitlEntityRemapEntry] = Field(default_factory=list)
    waive_mandatory_node_ids: list[str] = Field(default_factory=list)
    reason: str = ""


class HitlBStoryJudgementRequest(BaseModel):
    action: Literal["force_resolve", "reject"]
    resolved_b_stories: list[str] = Field(default_factory=list)
    resolution_evidence_event_ids: list[str] = Field(default_factory=list)
    resolution_analysis: str = ""
    reject_resume_from: str = "extraction_gate"
    reason: str = ""


class HitlAnchorDelayRequest(BaseModel):
    anchor_id: str
    new_chapter_target: int = Field(..., ge=1)
    reason: str = ""


class HitlContextPruneRequest(BaseModel):
    """Overwrite assembled context slices after human trimming."""

    bible_context: Optional[str] = None
    graph_context: Optional[str] = None
    vector_context: Optional[str] = None
    recent_chapter_context: Optional[str] = None
    previous_chapter_summary: Optional[str] = None
    graph_rag_context_tier: Optional[int] = Field(default=None, ge=0, le=2)
    reason: str = ""
