from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional, Union

MacroCastRole = Literal["protagonist", "supporting", "antagonist"]

AiFreedomLevel = Literal["strict", "balanced", "wild"]

StoryOutputLanguage = Literal["en", "zh-Hant", "zh-Hans"]

from pydantic import BaseModel, Field, field_validator, model_validator


def _coerce_tags_list(v: Any) -> list[str]:
    if v is None:
        return []
    if not isinstance(v, list):
        return []
    out: list[str] = []
    seen_lower: set[str] = set()
    for x in v:
        s = str(x).strip()
        if not s:
            continue
        k = s.casefold()
        if k not in seen_lower:
            seen_lower.add(k)
            out.append(s)
    return out


def _coerce_metadata_dict(v: Any) -> dict[str, Any]:
    if v is None or v == {}:
        return {}
    if isinstance(v, dict):
        return dict(v)
    return {}


class NodeType(str, Enum):
    CHARACTER = "CHARACTER"
    PERSONA = "PERSONA"
    LOCATION = "LOCATION"
    ITEM = "ITEM"
    CONCEPT = "CONCEPT"
    EPOCH = "EPOCH"
    EVENT = "EVENT"
    RULE = "RULE"


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
    ENFORCED_IN = "ENFORCED_IN"
    RESTRICTS = "RESTRICTS"
    EXEMPT_FROM = "EXEMPT_FROM"


class BaseNode(BaseModel):
    node_id: str = Field(..., description="Global unique node ID, such as char_001.")
    node_type: NodeType
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(
        default_factory=list,
        description="Free-form labels (e.g. weapon, faction); do not invent new node_type.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON-serializable extras; nested structures allowed in app layer, stored as JSON in Neo4j.",
    )

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_node_tags(cls, v: Any) -> list[str]:
        return _coerce_tags_list(v)

    @field_validator("metadata", mode="before")
    @classmethod
    def normalize_node_metadata(cls, v: Any) -> dict[str, Any]:
        return _coerce_metadata_dict(v)


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


class RuleNode(BaseNode):
    node_type: Literal[NodeType.RULE] = NodeType.RULE
    description: str = ""
    penalty: str | None = None
    is_active: bool = True


GraphNode = Union[
    CharacterNode,
    PersonaNode,
    EpochNode,
    LocationNode,
    ItemNode,
    EventNode,
    ConceptNode,
    RuleNode,
]


class EnforcedRuleContext(BaseModel):
    """One RULE active for the current POV location/epoch (for prompt injection)."""

    rule_id: str
    canonical_name: str
    description: str
    penalty: str | None = None
    restrict_target_names: list[str] = Field(default_factory=list)
    exempt_character_names: list[str] = Field(default_factory=list)


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
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_edge_tags(cls, v: Any) -> list[str]:
        return _coerce_tags_list(v)

    @field_validator("metadata", mode="before")
    @classmethod
    def normalize_edge_metadata(cls, v: Any) -> dict[str, Any]:
        return _coerce_metadata_dict(v)


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
    branch_count_override: int | None = Field(
        default=None,
        ge=1,
        le=64,
        description="Optional manual override for generated branch storyline count in macro compile.",
    )
    plan_retry_limit: int = Field(default=3, ge=0, le=20)
    draft_loop_retry_limit: int = Field(default=3, ge=0, le=20)
    output_language: StoryOutputLanguage = Field(
        default="zh-Hant",
        description="Natural-language output for generated story content, outlines, feedback, and extractions.",
    )


class StoryPatch(BaseModel):
    """Partial update allowed only before any workflow run (enforced in API/service)."""

    title: str | None = None
    premise: str | None = None
    target_total_words: int | None = Field(default=None, ge=1)
    branch_count_override: int | None = Field(default=None, ge=1, le=64)
    plan_retry_limit: int | None = Field(default=None, ge=0, le=20)
    draft_loop_retry_limit: int | None = Field(default=None, ge=0, le=20)
    macro_author_notes: str | None = None
    cast_seed: list[StoryCastSeedEntry] | None = None
    output_language: StoryOutputLanguage | None = Field(
        default=None,
        description="When omitted, existing DB value is preserved (PATCH must not null out).",
    )


class AuthorExtractionSurfaceHintEntry(BaseModel):
    node_id: str
    surface_forms: list[str] = Field(default_factory=list)


class ChapterRunRequest(BaseModel):
    """Optional body for POST .../chapters/{n}/run."""

    author_chapter_plan: str = Field(default="", max_length=2000)
    # New dual-track inputs (prefer these over author_chapter_plan).
    chapter_outline: str = Field(default="", max_length=2000)
    chapter_hard_rules: str = Field(default="", max_length=8000)
    ai_freedom_level: AiFreedomLevel = Field(
        default="balanced",
        description="strict: honor human outline where specified; wild: more invention on gaps.",
    )
    extraction_surface_hints: list[AuthorExtractionSurfaceHintEntry] = Field(
        default_factory=list,
        description="Optional surface-form hints merged into run state before the graph starts (not a HITL pause action).",
    )
    waive_mandatory_node_ids: list[str] = Field(
        default_factory=list,
        description="Optional mandatory node ids to waive for extraction gate (same merge as extraction hints).",
    )
    selected_anchor_ids: list[str] = Field(
        default_factory=list,
        description="Optional human/director-selected anchor ids for this chapter (max 2).",
    )
    next_anchor_ids: list[str] = Field(
        default_factory=list,
        description="Optional post-chapter navigation anchor ids (must remain reachable).",
    )

    @field_validator("ai_freedom_level", mode="before")
    @classmethod
    def _coerce_ai_freedom_level(cls, v: Any) -> str:
        if v is None or v == "":
            return "balanced"
        s = str(v).strip().lower()
        if s in ("strict", "balanced", "wild"):
            return s
        return "balanced"


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
    chapter_target: int = 0
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
    personality: str = Field(default="", description="Core personality and temperament traits.")
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

    @model_validator(mode="before")
    @classmethod
    def migrate_motivation_to_personality(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        v = dict(value)
        if not str(v.get("personality") or "").strip() and str(v.get("motivation") or "").strip():
            v["personality"] = str(v.get("motivation") or "")
        v.pop("motivation", None)
        return v


class StoryCastMemberStored(BaseModel):
    """Persisted cast row + graph node id after macro compile."""

    node_id: str
    canonical_name: str
    role: MacroCastRole
    short_bio: str = ""
    aliases: list[str] = Field(default_factory=list)
    age: str = ""
    personality: str = ""
    core_motivation: str = ""
    speech_style: str = ""
    fatal_flaw: str = ""
    quirks_and_habits: str = ""
    core_value: str = ""
    arc_history: list["CharacterArcMilestone"] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def migrate_motivation_to_personality(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        v = dict(value)
        if not str(v.get("personality") or "").strip() and str(v.get("motivation") or "").strip():
            v["personality"] = str(v.get("motivation") or "")
        v.pop("motivation", None)
        return v


class CharacterArcMilestone(BaseModel):
    trigger_event_id: str = ""
    trigger_event_summary: str = ""
    chapter_id: int = 0
    old_personality: str = ""
    new_personality: str = ""
    old_speech_style: str = ""
    new_speech_style: str = ""
    source: Literal["HITL", "PLANNER", "SYSTEM"] = "SYSTEM"
    reason: str = ""
    updated_at: str = ""


class CharacterEvolutionRequest(BaseModel):
    node_id: str
    trigger_event_id: str = ""
    trigger_event_summary: str = ""
    new_personality: str = ""
    new_speech_style: str = ""
    reason: str = ""
    source: Literal["HITL", "PLANNER", "SYSTEM"] = "HITL"


class StateAnchor(BaseModel):
    """Legacy runtime compatibility anchor row (DAG compile still emits anchor_nodes as source of truth)."""

    anchor_id: str
    story_id: str
    volume_id: str
    title: str
    description: str
    target_state: dict[str, Any]
    chapter_target: int = 0
    priority: int = 1


class MacroPlanPut(BaseModel):
    """Full replacement of macro-planned artifacts (manual edit; same persistence as macro compile)."""

    bible: dict[str, Any] = Field(default_factory=dict)
    volumes: list[VolumePlan] = Field(..., min_length=1)
    storylines: list["Storyline"] = Field(default_factory=list)
    anchor_nodes: list["AnchorNode"] = Field(..., min_length=1)
    cast: list[StoryCastMemberStored] = Field(default_factory=list)
    protagonist_character_id: str | None = None


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


class PlotSummarySource(str, Enum):
    """Provenance for chapter_summaries.plot_summary (UI + regenerate flow)."""

    CHAPTER_SUMMARIZER_LLM = "CHAPTER_SUMMARIZER_LLM"
    FALLBACK_EXTRACTION = "FALLBACK_EXTRACTION"
    FALLBACK_DRAFT = "FALLBACK_DRAFT"
    FALLBACK_DIRECTIVE = "FALLBACK_DIRECTIVE"
    PLACEHOLDER = "PLACEHOLDER"
    UNKNOWN = "UNKNOWN"


class StorylineTier(str, Enum):
    MAIN = "MAIN"
    USER_EDIT = "USER_EDIT"
    S_TIER = "S_TIER"
    A_TIER = "A_TIER"
    B_TIER = "B_TIER"


class AnchorStatus(str, Enum):
    LOCKED = "LOCKED"
    UNLOCKED = "UNLOCKED"
    RESOLVED = "RESOLVED"


class Storyline(BaseModel):
    id: str
    type: StorylineTier
    title: str
    overall_goal: str
    involved_entities: list[str] = Field(default_factory=list)


class AnchorNode(BaseModel):
    id: str
    storyline_ids: list[str] = Field(default_factory=list)
    volume_id: str
    node_kind: Literal["NORMAL", "FORK", "MERGE", "CHECKPOINT", "ENDING"] = "NORMAL"
    title: str
    description: str
    depends_on: list[str] = Field(default_factory=list)
    status: AnchorStatus = AnchorStatus.LOCKED


class StoryMapState(BaseModel):
    resolved_anchors: list[str] = Field(default_factory=list)
    active_anchors: list[str] = Field(default_factory=list)
    anchor_candidates: list[str] = Field(default_factory=list)


class BStoryType(str, Enum):
    FETCH_QUEST = "FETCH_QUEST"
    RELATIONSHIP_DRAMA = "RELATIONSHIP_DRAMA"
    ENVIRONMENTAL_HAZARD = "ENVIRONMENTAL_HAZARD"
    LORE_DISCOVERY = "LORE_DISCOVERY"
    INTERNAL_CONFLICT = "INTERNAL_CONFLICT"
    UNKNOWN = "UNKNOWN"


class MacroPlanOutput(BaseModel):
    total_chapters: int = 12
    bible: dict[str, Any] = Field(
        default_factory=dict,
        description="Generated story bible (general_world_lore markdown, story_genre, etc.).",
    )
    volumes: list[MacroVolumePlanDraft] = Field(default_factory=list)
    cast: list[MacroCastMember] = Field(default_factory=list)


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
    selected_anchor_ids: list[str] = Field(default_factory=list)
    next_anchor_ids: list[str] = Field(default_factory=list)
    b_story_directive: Optional[str] = None
    b_story_type: Optional[BStoryType] = None
    new_elements_to_introduce: list[DirectorNewElement] = Field(default_factory=list)
    request_new_b_story: Optional[DirectorNewBStoryRequest] = None
    state_operational_brief: str = Field(
        default="",
        max_length=2400,
        description="Status briefing for Planner: anchors distance, B-stories, continuity (not plot invention when outline is concrete).",
    )

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


class EventLinkType(str, Enum):
    CAUSAL = "CAUSAL"
    TEMPORAL = "TEMPORAL"


class EventLinkOrigin(str, Enum):
    HUMAN_GROUND_TRUTH = "HUMAN_GROUND_TRUTH"
    AI_INVENTION = "AI_INVENTION"


class EventLink(BaseModel):
    target_event_id: str
    link_type: EventLinkType = EventLinkType.TEMPORAL
    origin: Optional[EventLinkOrigin] = None


class EventOutline(BaseModel):

    event_id: str
    description: str
    caused_by_event_id: Optional[str] = None
    links: list[EventLink] = Field(default_factory=list)
    is_ai_invention: bool = False
    invention_scope: str = ""

    @model_validator(mode="after")
    def sync_legacy_cause_and_links(self) -> "EventOutline":
        normalized_links: list[EventLink] = []
        for link in self.links:
            target = (link.target_event_id or "").strip()
            if not target:
                continue
            normalized_links.append(
                EventLink(
                    target_event_id=target,
                    link_type=link.link_type,
                    origin=link.origin,
                )
            )
        self.links = normalized_links

        legacy_target = (self.caused_by_event_id or "").strip()
        if legacy_target and not any(
            link.target_event_id == legacy_target for link in self.links
        ):
            self.links.append(
                EventLink(
                    target_event_id=legacy_target,
                    link_type=EventLinkType.TEMPORAL,
                    origin=(
                        EventLinkOrigin.AI_INVENTION
                        if self.is_ai_invention
                        else EventLinkOrigin.HUMAN_GROUND_TRUTH
                    ),
                )
            )

        if not legacy_target and self.links:
            self.caused_by_event_id = self.links[0].target_event_id
        return self


class BeatOutline(BaseModel):
    text: str
    is_ai_invention: bool = False
    invention_scope: str = ""


class ProposedCharacterProfile(BaseModel):
    """High-level character sheet for planned CHARACTER nodes (aligns with macro cast fields)."""

    personality: str = Field(default="", max_length=600)
    core_motivation: str = Field(default="", max_length=600)
    fatal_flaw: str = Field(default="", max_length=400)
    speech_style: str = Field(default="", max_length=240)
    quirks_and_habits: str = Field(default="", max_length=400)
    short_bio: str = Field(default="", max_length=500)
    age: str = Field(default="", max_length=48)
    core_value: str = Field(default="", max_length=600)


class ProposedGraphNode(BaseModel):
    """Planner-invented graph node for genesis; max 2 per chapter (enforced in planner_node)."""

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


class PlannerOutput(BaseModel):
    ground_truth_events: list[EventOutline]
    narrative_script: str
    target_word_count: int = Field(
        ...,
        ge=1,
        description="Chapter length target: English=en word count (whitespace tokens); Chinese=normalized alnum character count; must match draft_supervisor measurement.",
    )
    chapter_start_location: str = ""
    selected_anchor_ids: list[str] = Field(default_factory=list)
    next_anchor_ids: list[str] = Field(default_factory=list)
    author_goal: str = ""
    must_include_beats: list[str] = Field(default_factory=list)
    must_include_beat_outlines: list[BeatOutline] = Field(default_factory=list)
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
    character_evolution_requests: list[CharacterEvolutionRequest] = Field(default_factory=list)

    @model_validator(mode="after")
    def sync_beat_fields(self) -> "PlannerOutput":
        if not self.must_include_beat_outlines and self.must_include_beats:
            self.must_include_beat_outlines = [BeatOutline(text=beat) for beat in self.must_include_beats if beat]
        if not self.must_include_beats and self.must_include_beat_outlines:
            self.must_include_beats = [beat.text for beat in self.must_include_beat_outlines if beat.text]
        return self


class AlignmentOutput(BaseModel):
    final_ground_truth_events: list[EventOutline] = Field(default_factory=list)
    final_narrative_script: str = ""
    final_must_include_beats: list[str] = Field(default_factory=list)
    safe_chapter_rules: str = Field(
        default="",
        description="經過 POV 視角安全遮蔽後的硬性規則原文。",
    )
    alignment_log: str = Field(
        default="",
        description="內部審計日誌：記錄了哪些草稿內容因為違反規則而被修改。",
    )
    human_outline_conflict_notes: list[str] = Field(
        default_factory=list,
        description="Human outline or plan vs bible/graph/canon; surfaced to UI and plan_warnings.",
    )
    requires_hitl: bool = Field(
        default=False,
        description="當草稿出現複雜設定但缺乏人類規則時，設為 True 請求介入。",
    )
    hitl_reason: str | None = Field(
        default=None,
        description="若 requires_hitl=True，具體說明需要人類補充的規則內容。",
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


class AnchorResolutionOutput(BaseModel):
    resolution_analysis: str = Field(
        ...,
        min_length=20,
        description="Resolver reasoning about planned anchors and chapter draft.",
    )
    resolved_anchor_ids: list[str] = Field(default_factory=list)
    unresolved_anchor_ids: list[str] = Field(default_factory=list)
    chapter_matches_plan: bool = False
    evidence_summary: list[dict[str, Any]] = Field(default_factory=list)
    decision_reason: str = ""
    resolver_confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Resolver confidence (0..1). Use low values when evidence is ambiguous.",
    )
    requires_human_review: bool = Field(
        default=False,
        description="True only when resolver is uncertain and requests HITL adjudication.",
    )


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
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tags", mode="before")
    @classmethod
    def _v_tags(cls, v: Any) -> list[str]:
        return _coerce_tags_list(v)

    @field_validator("metadata", mode="before")
    @classmethod
    def _v_metadata(cls, v: Any) -> dict[str, Any]:
        return _coerce_metadata_dict(v)


class ExtractedRelation(BaseModel):
    source_node_id: str = ""
    source_name: str = ""
    relation_type: EdgeType
    target_node_id: str = ""
    target_name: str = ""
    context_details: str = ""
    is_truth: bool = True
    is_public: bool = False
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tags", mode="before")
    @classmethod
    def _v_rel_tags(cls, v: Any) -> list[str]:
        return _coerce_tags_list(v)

    @field_validator("metadata", mode="before")
    @classmethod
    def _v_rel_metadata(cls, v: Any) -> dict[str, Any]:
        return _coerce_metadata_dict(v)


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
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("tags", mode="before")
    @classmethod
    def _v_cand_tags(cls, v: Any) -> list[str]:
        return _coerce_tags_list(v)

    @field_validator("metadata", mode="before")
    @classmethod
    def _v_cand_metadata(cls, v: Any) -> dict[str, Any]:
        return _coerce_metadata_dict(v)


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
    hitl_context: Optional["HitlContextPayload"] = Field(
        default=None,
        description="BFF view when paused for HITL; null when not waiting.",
    )


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


class GraphRAGAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=4000)
    active_epoch_id: str = "epoch_present"
    pov_character_id: str = "char_public_observer"
    top_k: int = Field(default=5, ge=1, le=20)
    context_hop_tier: int = Field(default=2, ge=0, le=2)


class GraphRAGEvaluateRequest(BaseModel):
    condition_desc: str = Field(..., min_length=1, max_length=4000)
    active_epoch_id: str = "epoch_present"
    pov_character_id: str = "char_public_observer"
    top_k: int = Field(default=5, ge=1, le=20)
    context_hop_tier: int = Field(default=2, ge=0, le=2)


class GraphRAGEvaluateOutput(BaseModel):
    resolved: bool
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str = Field(default="", max_length=4000)


class HitlReason:
    """Stable string ids for workflow state hitl_reason (avoid magic strings scattered in code)."""

    PLAN_LOOP_EXCEEDED = "Plan_Loop_Exceeded"
    DRAFT_LOOP_EXCEEDED = "Draft_Loop_Exceeded"
    EXTRACTION_GATE_FAILED = "Extraction_Gate_Failed"
    B_STORY_RESOLUTION_FAILED = "B_Story_Resolution_Failed"
    B_STORY_COOLDOWN_VIOLATION = "B_Story_Cooldown_Violation"
    ANCHOR_RESOLUTION_FAILED = "Anchor_Resolution_Failed"
    RESOLUTION_TACTIC_COOLDOWN_VIOLATION = "Resolution_Tactic_Cooldown_Violation"
    ENDING_VIBE_COOLDOWN_VIOLATION = "Ending_Vibe_Cooldown_Violation"
    CONTEXT_LENGTH_EXCEEDED = "Context_Length_Exceeded"
    ALIGNMENT_RULES_REQUIRED = "Alignment_Rules_Required"
    OUTPUT_LANGUAGE_MISMATCH = "Output_Language_Mismatch"


HitlContextPayloadType = Literal[
    "alignment",
    "extraction_remap",
    "draft_loop",
    "context_prune",
    "output_language",
    "generic",
]


class HitlContextMetadata(BaseModel):
    """Typed bag for frontend-specific HITL context (keeps payload extensible)."""

    payload_type: HitlContextPayloadType = "generic"
    unknown_entities: list[dict[str, Any]] = Field(default_factory=list)
    graph_rag_context_tier: int | None = Field(
        default=None,
        description="Product-tier 0=full .. 2=aggressive when payload_type=context_prune.",
    )
    expected_output_language: str | None = Field(
        default=None,
        description="Story output_language code when payload_type=output_language.",
    )
    language_detection_summary: str | None = Field(
        default=None,
        description="Brief script-count summary when payload_type=output_language.",
    )


class HitlActionRecord(BaseModel):
    """One persisted human action during a paused workflow run."""

    action_id: str
    run_id: str
    action_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class HitlContextPayload(BaseModel):
    """BFF payload when workflow is WAITING_HITL (stable fields for dynamic forms)."""

    primary_issue: str = ""
    supervisor_feedbacks: list[str] = Field(default_factory=list)
    conflict_notes: list[str] = Field(default_factory=list)
    problematic_draft_snippet: str = ""
    context_metadata: HitlContextMetadata = Field(default_factory=HitlContextMetadata)


class HitlDecisionRequest(BaseModel):
    option_id: str
    rationale: str = ""


class HitlOutlineEditRequest(BaseModel):
    ground_truth_events: list[EventOutline]
    narrative_script: Optional[str] = None
    reason: str = ""


class HitlStateInjectionRequest(BaseModel):
    mutations: list[Union[NodeMutation, EdgeMutation]] = Field(default_factory=list)
    chapter_hard_rules: str = Field(
        default="",
        max_length=8000,
        description="Optional: update state.chapter_hard_rules before resume (for alignment HITL).",
    )
    resume_from: str = ""
    reason: str = ""
    this_chapter_pacing_limit: str = Field(
        default="",
        max_length=2000,
        description="Human pacing brake text; planner must not resolve the chapter arc this chapter.",
    )
    future_anchor_title: str = Field(default="", max_length=500)
    future_anchor_description: str = Field(default="", max_length=4000)
    chapters_to_delay: int | None = Field(
        default=None,
        ge=0,
        description="Chapters until future anchor triggers; None defaults to 0 at apply time.",
    )
    cast_evolutions: list[CharacterEvolutionRequest] = Field(default_factory=list)


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


class HitlAnchorResolutionRequest(BaseModel):
    action: Literal["force_resolve", "rewrite", "delay_anchor"]
    resolved_anchor_ids: list[str] = Field(default_factory=list)
    delayed_anchor_ids: list[str] = Field(default_factory=list)
    reject_resume_from: str = "planner"
    reason: str = ""


class HitlAnchorDelayRequest(BaseModel):
    anchor_id: str
    action: Literal["defer"] = "defer"
    reason: str = ""


class HitlContextPruneRequest(BaseModel):
    """Human picks context assembly tier; backend re-assembles context on resume (no raw string overrides)."""

    graph_rag_context_tier: int = Field(
        ...,
        ge=0,
        le=2,
        description="Product semantics: 0=full context, 1=medium trim, 2=aggressive trim (mapped in service).",
    )
    reason: str = ""
