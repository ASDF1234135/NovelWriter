from __future__ import annotations

from copy import deepcopy
import logging
import re
import sqlite3
from uuid import uuid4

from app.domain.schema import (
    AuthorExtractionSurfaceHintEntry,
    BStoryResolutionOutput,
    HitlAnchorDelayRequest,
    HitlBStoryJudgementRequest,
    HitlContextPruneRequest,
    HitlDecisionRequest,
    HitlDirectorPatchRequest,
    HitlDraftEditRequest,
    HitlExtractionHintsRequest,
    HitlExtractionRemapRequest,
    HitlOutlineEditRequest,
    HitlReason,
    HitlStateInjectionRequest,
    MacroPlanPut,
    NodeMutation,
    NodeType,
    StateAnchor,
    StateTransactionStatus,
    StateUpdaterOutput,
    StoryCastMemberStored,
    StoryInput,
    StoryOutputLanguage,
    StoryPatch,
    VolumePlan,
    WorkflowStatus,
)
from app.domain.state import apply_length_bounds_to_state, build_initial_state, normalize_workflow_state
from app.services.workflow.chapter_pipeline import extraction_substantiated_event_ids, validate_b_story_resolution
from app.services.workflow.constants import AUTHOR_CHAPTER_PLAN_MAX_CHARS, CHAPTER_HARD_RULES_MAX_CHARS
from app.repositories.sqlite.story_repository import StoryRepository
from app.repositories.sqlite.workflow_repository import WorkflowRepository
from app.services.anchor_service import AnchorService
from app.services.bible_service import BibleService
from app.services.graph_store import GraphStore
from app.services.llm import LLMClient
from app.services.vector_store import VectorStore
from app.services.workflow.bible_writing_notes import normalize_writing_note
from app.services.workflow.chapter_pacing import (
    build_ending_vibe_cooldown_constraint,
    build_resolution_cooldown_constraint,
    chapter_distance_to_anchor,
)
from app.services.workflow.context import WorkflowContext
from app.services.workflow.nodes.chapter_summarizer import (
    build_minimal_state_for_regenerate,
    persist_chapter_summary,
)
from app.services.workflow.output_language import (
    default_chapter_target_words,
    normalize_output_language,
    strip_leading_chapter_heading_line,
)
from app.services.workflow.graph import build_chapter_graph
from app.services.workflow.hitl_payload import build_hitl_context_payload, should_expose_hitl_context
from app.services.workflow.outline_binding import compute_outline_binding_mode

_ALLOWED_HITL_RESUME_NODES = frozenset(
    {
        "director",
        "planner",
        "logic_alignment",
        "author",
        "draft_supervisor",
        "reader",
        "graph_rag",
        "extraction_gate",
        "copyeditor",
        "output_language_gate",
        "b_story_resolve",
        "profile_expander",
        "state_updater",
    }
)


def _refresh_unachieved_anchors(story_repository: StoryRepository, state: dict) -> None:
    chapter_id = int(state["chapter_id"])
    story_id = str(state["story_id"])
    raw = story_repository.list_anchors(story_id)
    unachieved = [a for a in raw if int(a["chapter_target"]) >= chapter_id]
    state["unachieved_anchors"] = unachieved
    state["target_anchor_id"] = str(unachieved[0]["anchor_id"]) if unachieved else None
    state["distance_to_anchor"] = chapter_distance_to_anchor(chapter_id, unachieved)


def _merge_surface_hints(state: dict, entries: list) -> None:
    by_id: dict[str, list[str]] = {}
    for h in state.get("author_extraction_surface_hints") or []:
        if not isinstance(h, dict):
            continue
        nid = str(h.get("node_id") or "").strip()
        if not nid:
            continue
        forms = [s for s in (h.get("surface_forms") or []) if isinstance(s, str) and s]
        by_id[nid] = forms
    for ent in entries:
        nid = str(ent.node_id).strip()
        if not nid:
            continue
        forms = [s for s in ent.surface_forms if isinstance(s, str) and s]
        prev = by_id.get(nid, [])
        merged = list(dict.fromkeys(prev + forms))
        by_id[nid] = merged
    state["author_extraction_surface_hints"] = [{"node_id": k, "surface_forms": v} for k, v in by_id.items()]


def _internal_graph_rag_tier_from_product(product_tier: int) -> int:
    """Map UI tier 0=full .. 2=aggressive to graph_rag internal (higher = wider caps)."""
    return max(0, min(2, 2 - int(product_tier)))


def _pick_volume_id_for_chapter(story_repository: StoryRepository, story_id: str, chapter_id: int) -> str:
    vols = story_repository.list_volumes(story_id)
    for v in vols:
        cs, ce = int(v["chapter_start"]), int(v["chapter_end"])
        if cs <= chapter_id <= ce:
            return str(v["volume_id"])
    return str(vols[0]["volume_id"]) if vols else "vol_unknown"


def _merge_hitl_future_anchor(
    story_repository: StoryRepository,
    story_id: str,
    chapter_id: int,
    title: str,
    description: str,
    chapters_to_delay: int | None,
) -> None:
    if not (title or "").strip() and not (description or "").strip():
        return
    delay = 0 if chapters_to_delay is None else int(chapters_to_delay)
    target_chapter = chapter_id + delay
    t = (title or "").strip() or (description or "").strip()[:120] or "未命名錨點"
    d = (description or "").strip()
    anchor_id = f"{story_id}_hitl_anchor_{uuid4().hex[:10]}"
    volume_id = _pick_volume_id_for_chapter(story_repository, story_id, chapter_id)
    rows = story_repository.list_anchors(story_id)
    anchors: list[StateAnchor] = []
    for row in rows:
        ts = row.get("target_state_json")
        if not isinstance(ts, dict):
            ts = {}
        vid = str(row.get("volume_id") or volume_id).strip() or volume_id
        anchors.append(
            StateAnchor(
                anchor_id=str(row["anchor_id"]),
                story_id=story_id,
                volume_id=vid,
                title=str(row.get("title") or ""),
                description=str(row.get("description") or ""),
                target_state=ts,
                chapter_target=int(row["chapter_target"]),
                priority=int(row.get("priority") or 1),
            )
        )
    anchors.append(
        StateAnchor(
            anchor_id=anchor_id,
            story_id=story_id,
            volume_id=volume_id,
            title=t,
            description=d,
            target_state={"source": "hitl_future_anchor"},
            chapter_target=target_chapter,
            priority=1,
        )
    )
    story_repository.store_anchors(story_id, anchors)


def _apply_abort_and_restart_chapter_state(story_repository: StoryRepository, state: dict) -> None:
    """Discard AI chapter progress and restart planning; keep human outline/hard rules."""
    outline = str(state.get("chapter_outline") or state.get("author_chapter_plan") or "").strip()
    hard = str(state.get("chapter_hard_rules") or "").strip()
    freedom = str(state.get("ai_freedom_level") or "balanced").strip().lower()
    if freedom not in ("strict", "balanced", "wild"):
        freedom = "balanced"
    binding = str(state.get("outline_binding_mode") or "ABSENT").strip() or "ABSENT"

    story_id = str(state["story_id"])
    chapter_id = int(state["chapter_id"])
    trace_id = str(state.get("trace_id") or uuid4())
    story = story_repository.get_story(story_id) or {}
    pov_raw = (story.get("protagonist_character_id") or "").strip()
    pov_character_id = pov_raw if pov_raw else "char_public_observer"

    unachieved = [
        a
        for a in story_repository.list_anchors(story_id)
        if int(a["chapter_target"]) >= chapter_id
    ]
    fresh = build_initial_state(
        story_id=story_id,
        chapter_id=chapter_id,
        unachieved_anchors=unachieved,
        trace_id=trace_id,
        plan_retry_limit=int(story.get("plan_retry_limit", 3)),
        draft_loop_retry_limit=int(story.get("draft_loop_retry_limit", 3)),
        pov_character_id=pov_character_id,
        author_chapter_plan=outline[:AUTHOR_CHAPTER_PLAN_MAX_CHARS],
        chapter_outline=outline[:AUTHOR_CHAPTER_PLAN_MAX_CHARS],
        chapter_hard_rules=hard[:CHAPTER_HARD_RULES_MAX_CHARS],
        ai_freedom_level=freedom,
        outline_binding_mode=binding,
    )
    # Carry over run bootstrap context that start_run_chapter would recompute.
    for key in (
        "previous_chapter_tail_excerpt",
        "recent_b_story_types",
        "all_milestone_summaries",
        "recent_chapter_summaries",
        "global_conflict_type_top3",
        "global_resolution_method_top3",
        "resolution_cooldown_constraint",
        "ending_vibe_cooldown_constraint",
        "narrative_directive",
        "tone_direction",
        "target_word_count",
    ):
        if key in state and state[key] not in (None, "", [], {}):
            fresh[key] = deepcopy(state[key]) if isinstance(state[key], (dict, list)) else state[key]

    bible = story.get("bible_json") or {}
    fresh["active_b_stories"] = list(bible.get("active_b_stories") or [])
    fresh["lore_mysteries_progression"] = list(bible.get("lore_mysteries_progression") or [])
    fresh["writing_note"] = normalize_writing_note(bible.get("writing_note"))
    fresh["distance_to_anchor"] = chapter_distance_to_anchor(chapter_id, unachieved)
    normalize_workflow_state(fresh)
    fresh["story_output_language"] = normalize_output_language(str(story.get("output_language") or ""))
    apply_length_bounds_to_state(fresh)
    state.clear()
    state.update(fresh)


class HitlNotWaitingError(RuntimeError):
    """Raised when HITL APIs are called but the run is not paused for human input."""


class HitlExtractionHintsDisabledError(RuntimeError):
    """Surface hints must be sent on chapter run (ChapterRunRequest); /hitl/extraction-hints is disabled."""


class ChapterAlreadyCompletedError(RuntimeError):
    """Raised when attempting to run the full agent pipeline for a chapter already committed as completed."""


class StoryConfigurationLockedError(RuntimeError):
    """Raised when PATCH story is forbidden after workflow runs exist."""


class MacroCompileAlreadyRunningError(RuntimeError):
    """Raised when macro compile is requested while a compile is already in progress."""


class MacroPlanValidationError(ValueError):
    """Raised when manual macro plan payload fails structural checks."""


class ChapterSummaryRegenerateFailed(RuntimeError):
    """Raised when POST regenerate-summary cannot persist an LLM-backed chapter summary."""


logger = logging.getLogger(__name__)


def _existing_cast_node_ids(story: dict) -> list[str]:
    out: list[str] = []
    for raw in story.get("cast_json") or []:
        if not isinstance(raw, dict):
            continue
        node_id = str(raw.get("node_id") or "").strip()
        if node_id:
            out.append(node_id)
    return out


def _validate_macro_plan_put(body: MacroPlanPut) -> None:
    vol_by_id = {v.volume_id: v for v in body.volumes}
    if len(vol_by_id) != len(body.volumes):
        raise MacroPlanValidationError("Duplicate volume_id in volumes")
    for v in body.volumes:
        if v.chapter_end < v.chapter_start:
            raise MacroPlanValidationError(
                f"Volume {v.volume_id}: chapter_end must be >= chapter_start"
            )
        if v.chapter_start < 1:
            raise MacroPlanValidationError(f"Volume {v.volume_id}: chapter_start must be >= 1")
    seen_anchor: set[str] = set()
    for a in body.anchors:
        if a.anchor_id in seen_anchor:
            raise MacroPlanValidationError(f"Duplicate anchor_id: {a.anchor_id}")
        seen_anchor.add(a.anchor_id)
        vol = vol_by_id.get(a.volume_id)
        if not vol:
            raise MacroPlanValidationError(f"Anchor {a.anchor_id}: unknown volume_id {a.volume_id}")
        if a.chapter_target < vol.chapter_start or a.chapter_target > vol.chapter_end:
            raise MacroPlanValidationError(
                f"Anchor {a.anchor_id}: chapter_target {a.chapter_target} "
                f"outside volume range [{vol.chapter_start}, {vol.chapter_end}]"
            )
    prot = (body.protagonist_character_id or "").strip()
    if prot:
        cast_ids = {c.node_id for c in body.cast}
        if prot not in cast_ids:
            raise MacroPlanValidationError("protagonist_character_id must match a cast member node_id")


def _cast_graph_description(member: StoryCastMemberStored) -> str:
    lines: list[str] = []
    if (member.short_bio or "").strip():
        lines.append(f"【故事身分】{member.short_bio.strip()}")
    if (member.age or "").strip():
        lines.append(f"【年齡】{member.age.strip()}")
    core = (member.core_motivation or "").strip()
    if core:
        lines.append(f"【核心動機】{core}")
    if (member.personality or "").strip():
        lines.append(f"【個性】{member.personality.strip()}")
    if (member.core_value or "").strip():
        lines.append(f"【核心價值】{member.core_value.strip()}")
    if (member.speech_style or "").strip():
        lines.append(f"【語感】{member.speech_style.strip()}")
    if (member.fatal_flaw or "").strip():
        lines.append(f"【致命缺陷】{member.fatal_flaw.strip()}")
    if (member.quirks_and_habits or "").strip():
        lines.append(f"【小習慣】{member.quirks_and_habits.strip()}")
    return "\n".join(lines) if lines else member.canonical_name


def _trim_to_sentence_boundary(text: str, max_chars: int) -> str:
    """Trim to <= max_chars, preferring punctuation boundaries to avoid chopping mid-sentence."""
    if len(text) <= max_chars:
        return text.strip()

    chunk = text[:max_chars]
    end_punct = ["。", "！", "？", "；", "…"]
    last_end = max((chunk.rfind(p) for p in end_punct), default=-1)
    if last_end > int(max_chars * 0.5):
        chunk = chunk[: last_end + 1]
    return chunk.strip()


def _extract_tail_excerpt(
    content: str,
    *,
    min_chars: int = 150,
    max_chars: int = 220,
    max_paragraphs: int = 3,
    max_total_paragraphs: int = 5,
) -> str:
    """
    Extract a trailing tail context excerpt from chapter content.

    Primary selection: last `max_paragraphs` paragraphs.
    If the excerpt is too short, we may include a few earlier paragraphs up to `max_total_paragraphs`.
    """
    if not content:
        return ""

    cleaned = strip_leading_chapter_heading_line(content)
    if not cleaned:
        return ""

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", cleaned) if p.strip()]
    if not paragraphs:
        return ""

    start_idx = max(0, len(paragraphs) - max_paragraphs)
    excerpt_paras = paragraphs[start_idx:]
    excerpt = "\n\n".join(excerpt_paras).strip()

    if len(excerpt) < min_chars and len(paragraphs) > len(excerpt_paras):
        start_idx2 = max(0, len(paragraphs) - max_total_paragraphs)
        excerpt_paras2 = paragraphs[start_idx2:]
        excerpt = "\n\n".join(excerpt_paras2).strip()

    excerpt = _trim_to_sentence_boundary(excerpt, max_chars=max_chars)
    return excerpt


def _ensure_hitl_waiting(state: dict) -> None:
    """Normalize minor drift between requires_hitl and workflow_status before applying HITL input."""
    ws = str(state.get("workflow_status") or "")
    req = bool(state.get("requires_hitl"))
    if ws == WorkflowStatus.WAITING_HITL.value:
        if not req:
            state["requires_hitl"] = True
        return
    if req:
        state["workflow_status"] = WorkflowStatus.WAITING_HITL.value
        return
    raise HitlNotWaitingError("Workflow is not waiting for HITL")


class WorkflowService:
    def __init__(
        self,
        story_repository: StoryRepository,
        workflow_repository: WorkflowRepository,
        bible_service: BibleService,
        anchor_service: AnchorService,
        graph_store: GraphStore,
        vector_store: VectorStore,
        llm_client: LLMClient,
    ) -> None:
        self.story_repository = story_repository
        self.workflow_repository = workflow_repository
        self.bible_service = bible_service
        self.anchor_service = anchor_service
        self.graph_store = graph_store
        self.vector_store = vector_store
        self.llm_client = llm_client

    def _build_context(self, run_id: str) -> WorkflowContext:
        wf_run = self.workflow_repository.get_run(run_id)
        story_row = self.story_repository.get_story(wf_run.story_id)
        ol = normalize_output_language(str(story_row.get("output_language") or "") if story_row else None)
        return WorkflowContext(
            story_repository=self.story_repository,
            workflow_repository=self.workflow_repository,
            bible_service=self.bible_service,
            anchor_service=self.anchor_service,
            graph_store=self.graph_store,
            vector_store=self.vector_store,
            llm_client=self.llm_client,
            run_id=run_id,
            output_language=ol,
        )

    def _execute_workflow(self, run_id: str, state: dict) -> dict:
        context = self._build_context(run_id)
        graph = build_chapter_graph(context)
        final_state = graph.invoke(state)
        self.workflow_repository.update_run(run_id, final_state)
        return final_state

    def create_story(self, story_input: StoryInput) -> dict:
        story_id = f"story_{uuid4().hex[:10]}"
        story = self.story_repository.create_story(story_id, story_input)
        self.graph_store.seed_story(story_id)
        return story

    def patch_story(self, story_id: str, patch: StoryPatch) -> dict:
        if self.workflow_repository.count_workflow_runs_for_story(story_id) > 0:
            raise StoryConfigurationLockedError(
                "故事已有章節工作流程紀錄，無法再修改專案設定；請在未執行 run_chapter 前調整。"
            )
        return self.story_repository.patch_story(story_id, patch)

    def delete_story(self, story_id: str) -> None:
        """Remove story from SQLite, workflow tables, in-memory/Neo4j graph, and vector index."""
        if not self.story_repository.get_story(story_id):
            raise KeyError(f"Story not found: {story_id}")
        self.workflow_repository.delete_all_for_story(story_id)
        self.story_repository.delete_story_cascade(story_id)
        self.graph_store.remove_story(story_id)
        self.vector_store.remove_story(story_id)

    def macro_compile(self, story_id: str) -> dict:
        story = self.story_repository.get_story(story_id)
        if not story:
            raise KeyError(f"Story not found: {story_id}")
        stale_cast_ids = _existing_cast_node_ids(story)
        raw_lang = str(story.get("output_language") or "").strip()
        ol: StoryOutputLanguage = normalize_output_language(raw_lang)
        story_input = StoryInput(
            title=story["title"],
            premise=story["premise"],
            bible={},
            macro_author_notes=str(story.get("macro_author_notes") or ""),
            cast_seed=list(story.get("cast_seed") or []),
            target_total_words=story["target_total_words"],
            plan_retry_limit=int(story.get("plan_retry_limit", 3)),
            draft_loop_retry_limit=int(story.get("draft_loop_retry_limit", 3)),
            output_language=ol,
        )
        volumes, anchors, cast, b_seed, bible_generated = self.anchor_service.compile_macro_plan(
            story_id, story_input, self.llm_client
        )
        self.story_repository.update_story_bible_json(story_id, bible_generated)
        self.story_repository.merge_active_b_stories_seed(story_id, b_seed)
        self.story_repository.store_volumes(story_id, volumes)
        self.story_repository.store_anchors(story_id, anchors)
        protagonist_id = next((c.node_id for c in cast if c.role == "protagonist"), "")
        self.story_repository.update_story_cast(story_id, cast, protagonist_id)
        self.graph_store.clear_macro_cast_characters(story_id, include_node_ids=stale_cast_ids)
        cast_mutations = [
            NodeMutation(
                action="CREATE_NODE",
                node_id=member.node_id,
                node_type=NodeType.CHARACTER,
                properties={
                    "canonical_name": member.canonical_name,
                    "description": _cast_graph_description(member),
                    "aliases": member.aliases,
                    "is_alive": True,
                },
            )
            for member in cast
        ]
        self.graph_store.apply_mutations(story_id, cast_mutations)
        story_after = self.story_repository.get_story(story_id) or {}
        return {
            "story_id": story_id,
            "bible": bible_generated,
            "macro_author_notes": str(story_after.get("macro_author_notes") or ""),
            "cast_seed": [
                s.model_dump(mode="json") for s in (story_after.get("cast_seed") or [])
            ],
            "volumes": [volume.model_dump(mode="json") for volume in volumes],
            "anchors": [anchor.model_dump(mode="json") for anchor in anchors],
            "cast": [member.model_dump(mode="json") for member in cast],
            "protagonist_character_id": protagonist_id,
        }

    def get_macro_snapshot(self, story_id: str) -> dict:
        """Read macro plan (volumes, anchors, cast) from SQLite without calling the LLM."""
        story = self.story_repository.get_story(story_id)
        if not story:
            raise KeyError(f"Story not found: {story_id}")
        vol_rows = self.story_repository.list_volumes(story_id)
        anc_rows = self.story_repository.list_anchors(story_id)
        volumes = [
            VolumePlan(
                volume_id=str(row["volume_id"]),
                title=str(row["title"]),
                summary=str(row["summary"]),
                chapter_start=int(row["chapter_start"]),
                chapter_end=int(row["chapter_end"]),
                target_volume_words=int(row.get("target_volume_words") or 0),
            ).model_dump(mode="json")
            for row in vol_rows
        ]
        anchors: list[dict] = []
        for row in anc_rows:
            ts = row.get("target_state_json")
            if not isinstance(ts, dict):
                ts = {}
            anchors.append(
                StateAnchor(
                    anchor_id=str(row["anchor_id"]),
                    story_id=str(row["story_id"]),
                    volume_id=str(row["volume_id"]),
                    title=str(row["title"]),
                    description=str(row["description"]),
                    target_state=ts,
                    chapter_target=int(row["chapter_target"]),
                    priority=int(row.get("priority") or 1),
                ).model_dump(mode="json")
            )
        cast_out: list[dict] = []
        for raw in story.get("cast_json") or []:
            if not isinstance(raw, dict):
                continue
            try:
                cast_out.append(StoryCastMemberStored.model_validate(raw).model_dump(mode="json"))
            except Exception:
                continue
        protagonist_id = str(story.get("protagonist_character_id") or "").strip()
        bible_out = story.get("bible_json") if isinstance(story.get("bible_json"), dict) else {}
        return {
            "story_id": story_id,
            "bible": bible_out,
            "macro_author_notes": str(story.get("macro_author_notes") or ""),
            "cast_seed": [s.model_dump(mode="json") for s in (story.get("cast_seed") or [])],
            "volumes": volumes,
            "anchors": anchors,
            "cast": cast_out,
            "protagonist_character_id": protagonist_id,
            "compiled": len(vol_rows) > 0,
            "macro_compile_status": str(story.get("macro_compile_status") or "IDLE"),
            "macro_compile_updated_at": str(story.get("macro_compile_updated_at") or ""),
            "macro_compile_error": str(story.get("macro_compile_error") or ""),
        }

    def put_macro_plan(self, story_id: str, body: MacroPlanPut) -> dict:
        story = self.story_repository.get_story(story_id)
        if not story:
            raise KeyError(f"Story not found: {story_id}")
        if self.workflow_repository.count_workflow_runs_for_story(story_id) > 0:
            raise StoryConfigurationLockedError(
                "故事已有章節工作流程紀錄，無法再修改宏觀規劃；請在未執行 run_chapter 前調整。"
            )
        stale_cast_ids = _existing_cast_node_ids(story)
        _validate_macro_plan_put(body)
        try:
            self.story_repository.update_story_bible_json(story_id, dict(body.bible or {}))
            self.story_repository.store_volumes(story_id, list(body.volumes))
            anchors = [
                StateAnchor(
                    anchor_id=a.anchor_id,
                    story_id=story_id,
                    volume_id=a.volume_id,
                    title=a.title,
                    description=a.description,
                    target_state=dict(a.target_state or {}),
                    chapter_target=a.chapter_target,
                    priority=a.priority,
                )
                for a in body.anchors
            ]
            self.story_repository.store_anchors(story_id, anchors)
            protagonist_id = (body.protagonist_character_id or "").strip()
            if not protagonist_id:
                protagonist_id = next((c.node_id for c in body.cast if c.role == "protagonist"), "")
            self.story_repository.update_story_cast(story_id, list(body.cast), protagonist_id)
            self.graph_store.clear_macro_cast_characters(story_id, include_node_ids=stale_cast_ids)
            cast_mutations = [
                NodeMutation(
                    action="CREATE_NODE",
                    node_id=member.node_id,
                    node_type=NodeType.CHARACTER,
                    properties={
                        "canonical_name": member.canonical_name,
                        "description": _cast_graph_description(member),
                        "aliases": member.aliases,
                        "is_alive": True,
                    },
                )
                for member in body.cast
            ]
            self.graph_store.apply_mutations(story_id, cast_mutations)
        except sqlite3.IntegrityError as exc:
            raise MacroPlanValidationError(
                "Macro plan contains IDs that violate DB uniqueness constraints "
                "(likely duplicated volume_id/anchor_id across stories)."
            ) from exc
        return self.get_macro_snapshot(story_id)

    def begin_macro_compile_async(self, story_id: str) -> None:
        """Acquire RUNNING lock or raise KeyError / MacroCompileAlreadyRunningError."""
        if not self.story_repository.get_story(story_id):
            raise KeyError(f"Story not found: {story_id}")
        if not self.story_repository.try_begin_macro_compile(story_id):
            raise MacroCompileAlreadyRunningError(
                "Macro compile is already running for this story."
            )

    def execute_macro_compile_background(self, story_id: str) -> None:
        """Run macro_compile and persist terminal status (BackgroundTasks entry point)."""
        try:
            self.macro_compile(story_id)
        except Exception as exc:
            self.story_repository.finish_macro_compile(
                story_id, success=False, error_message=str(exc)[:500]
            )
            logger.exception("macro_compile background failed for %s", story_id)
            return
        self.story_repository.finish_macro_compile(story_id, success=True)

    def run_chapter(
        self,
        story_id: str,
        chapter_id: int,
        *,
        author_chapter_plan: str = "",
        chapter_outline: str = "",
        chapter_hard_rules: str = "",
        ai_freedom_level: str = "balanced",
        extraction_surface_hints: list[AuthorExtractionSurfaceHintEntry] | None = None,
        waive_mandatory_node_ids: list[str] | None = None,
    ) -> dict:
        """Blocking: create run and execute graph to completion (tests / scripts)."""
        wf = self.start_run_chapter(
            story_id,
            chapter_id,
            author_chapter_plan=author_chapter_plan,
            chapter_outline=chapter_outline,
            chapter_hard_rules=chapter_hard_rules,
            ai_freedom_level=ai_freedom_level,
            extraction_surface_hints=extraction_surface_hints,
            waive_mandatory_node_ids=waive_mandatory_node_ids,
        )
        self.execute_stored_run(wf["run"]["run_id"])
        return self.get_workflow(wf["run"]["run_id"])

    def start_run_chapter(
        self,
        story_id: str,
        chapter_id: int,
        author_chapter_plan: str = "",
        chapter_outline: str = "",
        chapter_hard_rules: str = "",
        ai_freedom_level: str = "balanced",
        extraction_surface_hints: list[AuthorExtractionSurfaceHintEntry] | None = None,
        waive_mandatory_node_ids: list[str] | None = None,
    ) -> dict:
        """Create workflow run and persist initial state only (graph not executed yet)."""
        story = self.story_repository.get_story(story_id)
        if not story:
            raise KeyError(f"Story not found: {story_id}")
        existing = self.story_repository.get_chapter(story_id, chapter_id)
        if existing and (existing.get("status") or "").lower() == "completed":
            raise ChapterAlreadyCompletedError(
                f"Chapter {chapter_id} is already generated and stored (status=completed); "
                "full agent run is not allowed for this chapter."
            )
        unachieved_anchors = [
            anchor
            for anchor in self.story_repository.list_anchors(story_id)
            if anchor["chapter_target"] >= chapter_id
        ]
        pov_raw = (story.get("protagonist_character_id") or "").strip()
        pov_character_id = pov_raw if pov_raw else "char_public_observer"
        # Backward compatible:
        # - Prefer chapter_outline, fallback to legacy author_chapter_plan.
        outline = (chapter_outline or "").strip() or (author_chapter_plan or "").strip()
        outline = outline[:AUTHOR_CHAPTER_PLAN_MAX_CHARS]
        hard_rules = (chapter_hard_rules or "").strip()[:CHAPTER_HARD_RULES_MAX_CHARS]
        freedom = str(ai_freedom_level or "balanced").strip().lower()
        if freedom not in ("strict", "balanced", "wild"):
            freedom = "balanced"
        binding_mode = compute_outline_binding_mode(outline, outline)
        initial_state = build_initial_state(
            story_id=story_id,
            chapter_id=chapter_id,
            unachieved_anchors=unachieved_anchors,
            trace_id=str(uuid4()),
            plan_retry_limit=int(story.get("plan_retry_limit", 3)),
            draft_loop_retry_limit=int(story.get("draft_loop_retry_limit", 3)),
            pov_character_id=pov_character_id,
            author_chapter_plan=outline,
            chapter_outline=outline,
            chapter_hard_rules=hard_rules,
            ai_freedom_level=freedom,
            outline_binding_mode=binding_mode,
        )
        _ol = normalize_output_language(str(story.get("output_language") or ""))
        initial_state["story_output_language"] = _ol
        initial_state["target_word_count"] = default_chapter_target_words(_ol)

        # Tail-End Context Injection: provide the previous chapter trailing excerpt to this run.
        previous_tail = ""
        if chapter_id > 1:
            prev = self.story_repository.get_chapter(story_id, chapter_id - 1) or {}
            if (prev.get("status") or "").lower() == "completed":
                previous_tail = _extract_tail_excerpt(str(prev.get("content") or ""))
        initial_state["previous_chapter_tail_excerpt"] = previous_tail

        # B-Story Cooldown Pool: compute b-story types used in the previous 2 completed chapters.
        recent_types: list[str] = []
        try:
            for prev_chapter_id in (chapter_id - 1, chapter_id - 2):
                if prev_chapter_id < 1:
                    continue
                with self.workflow_repository.db.connection() as conn:
                    row = conn.execute(
                        """
                        SELECT run_id, current_state_json
                        FROM workflow_runs
                        WHERE story_id = ? AND chapter_id = ?
                          AND status = ?
                        ORDER BY updated_at DESC
                        LIMIT 1
                        """,
                        (story_id, prev_chapter_id, WorkflowStatus.COMPLETED.value),
                    ).fetchone()
                if not row:
                    continue
                prev_state = self.workflow_repository.db.loads(row["current_state_json"])
                raw_type = prev_state.get("b_story_type_selected") or prev_state.get("b_story_type")
                bdir = prev_state.get("b_story_directive") or ""
                if not raw_type and bdir:
                    # Fallback for older runs / mock path: try to match directive against active_b_story desc.
                    for bs in prev_state.get("active_b_stories") or []:
                        if not isinstance(bs, dict):
                            continue
                        desc = str(bs.get("desc") or "")
                        if desc and (desc in bdir or bdir in desc):
                            raw_type = bs.get("type")
                            break
                t = str(raw_type).strip() if raw_type is not None else ""
                if not t or t.upper() == "UNKNOWN":
                    continue
                if t not in recent_types:
                    recent_types.append(t)
                if len(recent_types) >= 2:
                    break
        except Exception:
            # Cooldown injection is best-effort; never break chapter start.
            pass
        initial_state["recent_b_story_types"] = recent_types

        # Director anti-repetition inputs:
        # - all milestones (macro pace memory)
        # - recent 3 chapter summaries (detail-level reminder)
        # - global top-3 frequencies (anti-pattern guardrails)
        try:
            initial_state["all_milestone_summaries"] = self.story_repository.list_all_milestones(story_id)
            initial_state["recent_chapter_summaries"] = self.story_repository.get_recent_chapter_summaries(
                story_id, int(chapter_id), limit=3
            )
            initial_state["global_conflict_type_top3"] = self.story_repository.global_top_conflict_type(story_id, top_k=3)
            initial_state["global_resolution_method_top3"] = self.story_repository.global_top_resolution_method(
                story_id, top_k=3
            )
            initial_state["resolution_cooldown_constraint"] = build_resolution_cooldown_constraint(
                initial_state["recent_chapter_summaries"]
            )
            initial_state["ending_vibe_cooldown_constraint"] = build_ending_vibe_cooldown_constraint(
                initial_state["recent_chapter_summaries"]
            )
        except Exception:
            # Best-effort: director prompt can still run without these.
            initial_state["all_milestone_summaries"] = []
            initial_state["recent_chapter_summaries"] = []
            initial_state["global_conflict_type_top3"] = []
            initial_state["global_resolution_method_top3"] = []
            initial_state["resolution_cooldown_constraint"] = {"active": False}
            initial_state["ending_vibe_cooldown_constraint"] = {"active": False}

        bible = story.get("bible_json") or {}
        initial_state["active_b_stories"] = list(bible.get("active_b_stories") or [])
        initial_state["lore_mysteries_progression"] = list(bible.get("lore_mysteries_progression") or [])
        initial_state["writing_note"] = normalize_writing_note(bible.get("writing_note"))
        initial_state["distance_to_anchor"] = chapter_distance_to_anchor(chapter_id, unachieved_anchors)
        normalize_workflow_state(initial_state)
        apply_length_bounds_to_state(initial_state)
        if extraction_surface_hints:
            _merge_surface_hints(initial_state, extraction_surface_hints)
        if waive_mandatory_node_ids:
            cur = {str(x).strip() for x in (initial_state.get("mandatory_extraction_skips") or []) if str(x).strip()}
            cur.update(str(x).strip() for x in waive_mandatory_node_ids if str(x).strip())
            initial_state["mandatory_extraction_skips"] = sorted(cur)
        run = self.workflow_repository.create_run(story_id, chapter_id, initial_state)
        return self.get_workflow(run.run_id)

    def execute_stored_run(self, run_id: str) -> None:
        """Resume graph from DB state (used after start_run_chapter or HITL)."""
        state = normalize_workflow_state(self.workflow_repository.get_run_state(run_id))
        try:
            self._execute_workflow(run_id, state)
        except Exception as exc:
            try:
                state = self.workflow_repository.get_run_state(run_id)
                state["workflow_status"] = WorkflowStatus.FAILED.value
                state["requires_hitl"] = False
                state["hitl_reason"] = str(exc)[:500]
                self.workflow_repository.update_run(run_id, state)
            except Exception:
                logger.exception(
                    "execute_stored_run could not persist FAILED state (run_id=%s)",
                    run_id,
                )
                raise
            # Do not re-raise: Starlette BackgroundTasks would log it as an ASGI error
            # even though the run is already marked FAILED in SQLite.
            logger.error(
                "Workflow run failed (run_id=%s)",
                run_id,
                exc_info=exc,
            )

    def get_workflow(self, run_id: str) -> dict:
        run = self.workflow_repository.get_run(run_id)
        state = normalize_workflow_state(self.workflow_repository.get_run_state(run_id))
        run_payload = run.model_dump(mode="json")
        if should_expose_hitl_context(state):
            hc = build_hitl_context_payload(state)
            run_payload["hitl_context"] = hc.model_dump(mode="json") if hc else None
        else:
            run_payload["hitl_context"] = None
        return {
            "run": run_payload,
            "state": state,
            "steps": self.workflow_repository.list_steps(run_id),
        }

    def list_chapters(self, story_id: str) -> list[dict]:
        story = self.story_repository.get_story(story_id)
        if not story:
            raise KeyError(f"Story not found: {story_id}")
        return self.story_repository.list_chapters(story_id)

    def list_hitl_actions(self, run_id: str, *, limit: int = 100, offset: int = 0) -> list[dict]:
        self.workflow_repository.get_run(run_id)
        return self.workflow_repository.list_hitl_actions(run_id, limit=limit, offset=offset)

    def get_chapter(self, story_id: str, chapter_id: int) -> dict:
        story = self.story_repository.get_story(story_id)
        if not story:
            raise KeyError(f"Story not found: {story_id}")
        chapter = self.story_repository.get_chapter(story_id, chapter_id)
        if not chapter:
            raise KeyError(f"Chapter not found: {story_id}:{chapter_id}")
        return chapter

    def regenerate_chapter_plot_summary(self, story_id: str, chapter_id: int) -> dict:
        """Re-run chapter_summarizer LLM path from stored chapter body (no workflow fallbacks)."""
        story = self.story_repository.get_story(story_id)
        if not story:
            raise KeyError(f"Story not found: {story_id}")
        chapter = self.story_repository.get_chapter(story_id, chapter_id)
        if not chapter:
            raise KeyError(f"Chapter not found: {story_id}:{chapter_id}")
        body = str(chapter.get("content") or "").strip()
        if not body:
            raise ValueError("Chapter has no content to summarize")

        ol = normalize_output_language(str(story.get("output_language") or ""))
        context = WorkflowContext(
            story_repository=self.story_repository,
            workflow_repository=self.workflow_repository,
            bible_service=self.bible_service,
            anchor_service=self.anchor_service,
            graph_store=self.graph_store,
            vector_store=self.vector_store,
            llm_client=self.llm_client,
            run_id=f"regenerate-summary:{story_id}:{chapter_id}",
            output_language=ol,
        )
        state = build_minimal_state_for_regenerate(
            story_id=story_id,
            chapter_id=chapter_id,
            chapter_content=body,
        )
        result = persist_chapter_summary(state, context, allow_fallback=False)
        if not result.get("written"):
            raise ChapterSummaryRegenerateFailed(str(result.get("error") or "Regenerate failed"))
        return {
            "regenerated": True,
            "plot_summary": result.get("plot_summary", ""),
            "plot_summary_source": result.get("plot_summary_source", ""),
        }

    def apply_hitl_decision(self, run_id: str, request: HitlDecisionRequest) -> None:
        state = normalize_workflow_state(self.workflow_repository.get_run_state(run_id))
        _ensure_hitl_waiting(state)
        prev_hitl_reason = str(state.get("hitl_reason", "") or "")
        self.workflow_repository.append_hitl_action(run_id, "decision", request.model_dump(mode="json"))

        if request.option_id == "ABORT_AND_RESTART":
            _apply_abort_and_restart_chapter_state(self.story_repository, state)
            state["requires_hitl"] = False
            state["hitl_reason"] = ""
            state["hitl_decision_mode"] = "NONE"
            state["pending_hitl_options"] = []
            state["workflow_status"] = WorkflowStatus.RUNNING.value
            state["resume_from"] = "planner"
            self.workflow_repository.update_run(run_id, state)
            return

        resume = str(state.get("resume_from") or "director")

        if request.option_id == "relax_word_count":
            state["target_word_count"] = max(800, int(state["target_word_count"] * 0.6))
            apply_length_bounds_to_state(state)
        if request.option_id in ("force_rewrite_plan", "allow_adjust_anchor"):
            state["plan_retry_count"] = 0
            state["plan_feedback"] = []
        if request.option_id == "force_approve_plan" and prev_hitl_reason == HitlReason.PLAN_LOOP_EXCEEDED:
            state["plan_retry_count"] = 0
            state["plan_feedback"] = []
            state["manual_plan_force_approve"] = True
            resume = "author"
        if request.option_id == "extraction_return_author" and prev_hitl_reason == HitlReason.EXTRACTION_GATE_FAILED:
            state["extraction_gate_failure_streak"] = 0
            resume = "author"
        if prev_hitl_reason == HitlReason.OUTPUT_LANGUAGE_MISMATCH:
            if request.option_id == "language_force_continue":
                state["output_language_hitl_waived"] = True
                resume = "output_language_gate"
            elif request.option_id == "language_return_author":
                state["output_language_hitl_waived"] = False
                note = (
                    "Output language check: chapter text likely does not match the story "
                    "output_language setting; rewrite the chapter body in the configured language."
                )
                draft_feedback = list(state.get("draft_feedback") or [])
                draft_feedback.append(
                    {
                        "attempt": int(state.get("draft_retry_count") or 0) + 1,
                        "violation": "OUTPUT_LANGUAGE",
                        "suggestion": "REWRITE",
                        "length_adjustment": "NONE",
                        "message": note,
                    }
                )
                state["draft_feedback"] = draft_feedback
                resume = "author"
        if request.option_id == "keep_current_logic":
            state["draft_loop_retry_count"] = 0
            state["draft_retry_count"] = 0
            state["reader_retry_count"] = 0

        if prev_hitl_reason == HitlReason.DRAFT_LOOP_EXCEEDED:
            state["draft_loop_retry_count"] = 0
            state["draft_retry_count"] = 0
            state["reader_retry_count"] = 0

        state["requires_hitl"] = False
        state["hitl_reason"] = ""
        state["hitl_decision_mode"] = "NONE"
        state["workflow_status"] = WorkflowStatus.RUNNING.value
        state["pending_hitl_options"] = []
        state["resume_from"] = resume
        self.workflow_repository.update_run(run_id, state)

    def handle_hitl_decision(self, run_id: str, request: HitlDecisionRequest) -> dict:
        self.apply_hitl_decision(run_id, request)
        self.execute_stored_run(run_id)
        return self.get_workflow(run_id)

    def apply_hitl_outline_edit(self, run_id: str, request: HitlOutlineEditRequest) -> None:
        state = normalize_workflow_state(self.workflow_repository.get_run_state(run_id))
        _ensure_hitl_waiting(state)
        if not request.ground_truth_events:
            raise ValueError("ground_truth_events must contain at least one event")
        prev_hitl_reason = str(state.get("hitl_reason", "") or "")
        state["ground_truth_events"] = [event.model_dump(mode="json") for event in request.ground_truth_events]
        if request.narrative_script:
            state["narrative_script"] = request.narrative_script
        state["requires_hitl"] = False
        state["hitl_reason"] = ""
        state["hitl_decision_mode"] = "NONE"
        state["pending_hitl_options"] = []
        state["workflow_status"] = WorkflowStatus.RUNNING.value
        if prev_hitl_reason == HitlReason.PLAN_LOOP_EXCEEDED:
            state["resume_from"] = "planner"
        else:
            state["resume_from"] = "author"
        self.workflow_repository.append_hitl_action(run_id, "outline_edit", request.model_dump(mode="json"))
        self.workflow_repository.update_run(run_id, state)

    def handle_hitl_outline_edit(self, run_id: str, request: HitlOutlineEditRequest) -> dict:
        self.apply_hitl_outline_edit(run_id, request)
        self.execute_stored_run(run_id)
        return self.get_workflow(run_id)

    def apply_hitl_state_injection(self, run_id: str, request: HitlStateInjectionRequest) -> None:
        state = normalize_workflow_state(self.workflow_repository.get_run_state(run_id))
        _ensure_hitl_waiting(state)
        prev_hitl_reason = str(state.get("hitl_reason", "") or "")
        if prev_hitl_reason == HitlReason.ALIGNMENT_RULES_REQUIRED:
            rules = (request.chapter_hard_rules or "").strip()
            if not rules:
                raise ValueError("Alignment HITL requires non-empty chapter_hard_rules")
        resume = (request.resume_from or state.get("resume_from", "author") or "author").strip()
        if resume not in _ALLOWED_HITL_RESUME_NODES:
            resume = str(state.get("resume_from", "author") or "author")
        if request.mutations:
            self.graph_store.apply_mutations(state["story_id"], request.mutations)
        if request.cast_evolutions:
            pending = list(state.get("pending_cast_evolutions") or [])
            pending.extend([row.model_dump(mode="json") for row in request.cast_evolutions])
            state["pending_cast_evolutions"] = pending
        pacing = (request.this_chapter_pacing_limit or "").strip()
        state["this_chapter_pacing_limit"] = pacing[:2000] if pacing else ""
        if (request.future_anchor_title or "").strip() or (request.future_anchor_description or "").strip():
            _merge_hitl_future_anchor(
                self.story_repository,
                str(state["story_id"]),
                int(state["chapter_id"]),
                request.future_anchor_title,
                request.future_anchor_description,
                request.chapters_to_delay,
            )
            _refresh_unachieved_anchors(self.story_repository, state)
        patched_rules = (request.chapter_hard_rules or "").strip()
        if patched_rules:
            state["chapter_hard_rules"] = patched_rules[:8000]
        state["requires_hitl"] = False
        state["hitl_reason"] = ""
        state["hitl_decision_mode"] = "NONE"
        state["pending_hitl_options"] = []
        state["workflow_status"] = WorkflowStatus.RUNNING.value
        if prev_hitl_reason == HitlReason.ALIGNMENT_RULES_REQUIRED:
            state["resume_from"] = "logic_alignment"
        else:
            state["resume_from"] = resume
        self.workflow_repository.append_hitl_action(run_id, "state_injection", request.model_dump(mode="json"))
        self.workflow_repository.update_run(run_id, state)

    def handle_hitl_state_injection(self, run_id: str, request: HitlStateInjectionRequest) -> dict:
        self.apply_hitl_state_injection(run_id, request)
        self.execute_stored_run(run_id)
        return self.get_workflow(run_id)

    def apply_hitl_draft_edit(self, run_id: str, request: HitlDraftEditRequest) -> None:
        state = normalize_workflow_state(self.workflow_repository.get_run_state(run_id))
        _ensure_hitl_waiting(state)
        resume = (request.resume_from or "reader").strip()
        if resume not in _ALLOWED_HITL_RESUME_NODES:
            resume = "reader"
        state["current_draft"] = request.chapter_content
        best_raw = (request.best_draft_content or "").strip()
        state["best_draft_content"] = best_raw if best_raw else request.chapter_content
        if not request.merge_extraction_hints:
            state["author_extraction_surface_hints"] = []
        state["requires_hitl"] = False
        state["hitl_reason"] = ""
        state["hitl_decision_mode"] = "NONE"
        state["pending_hitl_options"] = []
        state["workflow_status"] = WorkflowStatus.RUNNING.value
        state["resume_from"] = resume
        self.workflow_repository.append_hitl_action(run_id, "draft_edit", request.model_dump(mode="json"))
        self.workflow_repository.update_run(run_id, state)

    def handle_hitl_draft_edit(self, run_id: str, request: HitlDraftEditRequest) -> dict:
        self.apply_hitl_draft_edit(run_id, request)
        self.execute_stored_run(run_id)
        return self.get_workflow(run_id)

    def apply_hitl_director_patch(self, run_id: str, request: HitlDirectorPatchRequest) -> None:
        state = normalize_workflow_state(self.workflow_repository.get_run_state(run_id))
        _ensure_hitl_waiting(state)
        prev_hitl_reason = str(state.get("hitl_reason", "") or "")
        if request.chapter_type is not None:
            state["chapter_type"] = request.chapter_type
        if request.b_story_directive is not None:
            state["b_story_directive"] = request.b_story_directive
        if getattr(request, "b_story_type", None) is not None:
            state["b_story_type"] = request.b_story_type
        if request.new_elements_to_introduce is not None:
            state["new_elements_to_introduce"] = [
                e.model_dump(mode="json") for e in request.new_elements_to_introduce
            ]
        if request.request_new_b_story is not None:
            state["request_new_b_story"] = request.request_new_b_story.model_dump(mode="json")
        if request.narrative_directive is not None:
            state["narrative_directive"] = request.narrative_directive
        state["requires_hitl"] = False
        state["hitl_reason"] = ""
        state["hitl_decision_mode"] = "NONE"
        state["pending_hitl_options"] = []
        state["workflow_status"] = WorkflowStatus.RUNNING.value
        if prev_hitl_reason == HitlReason.DRAFT_LOOP_EXCEEDED:
            state["resume_from"] = "author"
        elif prev_hitl_reason == HitlReason.B_STORY_COOLDOWN_VIOLATION:
            state["resume_from"] = "graph_rag"
        else:
            state["resume_from"] = "planner"
        self.workflow_repository.append_hitl_action(run_id, "director_patch", request.model_dump(mode="json"))
        self.workflow_repository.update_run(run_id, state)

    def handle_hitl_director_patch(self, run_id: str, request: HitlDirectorPatchRequest) -> dict:
        self.apply_hitl_director_patch(run_id, request)
        self.execute_stored_run(run_id)
        return self.get_workflow(run_id)

    def apply_hitl_extraction_hints(self, run_id: str, request: HitlExtractionHintsRequest) -> None:
        raise HitlExtractionHintsDisabledError(
            "extraction_surface_hints and waive_mandatory_node_ids belong in POST /stories/{id}/chapters/{n}/run "
            "(ChapterRunRequest), not /hitl/extraction-hints."
        )

    def handle_hitl_extraction_hints(self, run_id: str, request: HitlExtractionHintsRequest) -> dict:
        self.apply_hitl_extraction_hints(run_id, request)
        self.execute_stored_run(run_id)
        return self.get_workflow(run_id)

    def apply_hitl_extraction_remap(self, run_id: str, request: HitlExtractionRemapRequest) -> None:
        state = normalize_workflow_state(self.workflow_repository.get_run_state(run_id))
        _ensure_hitl_waiting(state)
        if not request.entity_remaps and not request.waive_mandatory_node_ids:
            raise ValueError("Provide at least one entity remap or one waive_mandatory_node_ids entry")
        for row in request.entity_remaps:
            if not str(row.from_node_id).strip() or not str(row.to_node_id).strip():
                raise ValueError("Each entity remap must have non-empty from_node_id and to_node_id")
        manual = list(state.get("manual_entity_remap") or [])
        for row in request.entity_remaps:
            manual.append({"from_node_id": row.from_node_id, "to_node_id": row.to_node_id})
        state["manual_entity_remap"] = manual
        if request.waive_mandatory_node_ids:
            cur = {str(x).strip() for x in (state.get("mandatory_extraction_skips") or []) if str(x).strip()}
            cur.update(str(x).strip() for x in request.waive_mandatory_node_ids if str(x).strip())
            state["mandatory_extraction_skips"] = sorted(cur)
        state["extraction_gate_failure_streak"] = 0
        state["requires_hitl"] = False
        state["hitl_reason"] = ""
        state["hitl_decision_mode"] = "NONE"
        state["pending_hitl_options"] = []
        state["workflow_status"] = WorkflowStatus.RUNNING.value
        state["resume_from"] = "extraction_gate"
        state["post_polish_route"] = "resolve_subplots"
        self.workflow_repository.append_hitl_action(run_id, "extraction_remap", request.model_dump(mode="json"))
        self.workflow_repository.update_run(run_id, state)

    def handle_hitl_extraction_remap(self, run_id: str, request: HitlExtractionRemapRequest) -> dict:
        self.apply_hitl_extraction_remap(run_id, request)
        self.execute_stored_run(run_id)
        return self.get_workflow(run_id)

    def apply_hitl_b_story_judgement(self, run_id: str, request: HitlBStoryJudgementRequest) -> None:
        state = normalize_workflow_state(self.workflow_repository.get_run_state(run_id))
        _ensure_hitl_waiting(state)
        gt_ids = {str(e["event_id"]) for e in (state.get("ground_truth_events") or []) if e.get("event_id")}
        pending = state.get("pending_chapter_extraction") or {}
        valid_ids = extraction_substantiated_event_ids(pending, gt_ids)

        if request.action == "force_resolve":
            payload = {
                "resolution_analysis": request.resolution_analysis or "HITL force_resolve",
                "resolution_evidence_event_ids": list(request.resolution_evidence_event_ids),
                "resolved_b_stories": list(request.resolved_b_stories),
            }
            ok, err = validate_b_story_resolution(payload, valid_ids)
            if not ok:
                raise ValueError(err)
            state["b_story_resolution"] = BStoryResolutionOutput.model_validate(payload).model_dump(mode="json")
            state["resume_from"] = "state_updater"
        else:
            resume = (request.reject_resume_from or "extraction_gate").strip()
            if resume not in _ALLOWED_HITL_RESUME_NODES:
                resume = "extraction_gate"
            state["resume_from"] = resume
            fb = list(state.get("draft_feedback") or [])
            fb.append(
                {
                    "attempt": int(state.get("draft_retry_count", 0) or 0) + 1,
                    "violation": "B_STORY_REJECTED",
                    "suggestion": "REWRITE",
                    "message": request.reason or "副線核銷被人工打回，請依上下文調整正文或抽取結果。",
                }
            )
            state["draft_feedback"] = fb

        state["b_story_hitl_required"] = False
        state["b_story_resolution_hitl_candidate"] = {}
        state["requires_hitl"] = False
        state["hitl_reason"] = ""
        state["hitl_decision_mode"] = "NONE"
        state["pending_hitl_options"] = []
        state["workflow_status"] = WorkflowStatus.RUNNING.value
        self.workflow_repository.append_hitl_action(run_id, "b_story_judgement", request.model_dump(mode="json"))
        self.workflow_repository.update_run(run_id, state)

    def handle_hitl_b_story_judgement(self, run_id: str, request: HitlBStoryJudgementRequest) -> dict:
        self.apply_hitl_b_story_judgement(run_id, request)
        self.execute_stored_run(run_id)
        return self.get_workflow(run_id)

    def apply_hitl_anchor_delay(self, run_id: str, request: HitlAnchorDelayRequest) -> None:
        state = normalize_workflow_state(self.workflow_repository.get_run_state(run_id))
        _ensure_hitl_waiting(state)
        self.story_repository.update_anchor_chapter_target(
            state["story_id"], request.anchor_id, request.new_chapter_target
        )
        _refresh_unachieved_anchors(self.story_repository, state)
        state["plan_retry_count"] = 0
        state["plan_feedback"] = []
        state["requires_hitl"] = False
        state["hitl_reason"] = ""
        state["hitl_decision_mode"] = "NONE"
        state["pending_hitl_options"] = []
        state["workflow_status"] = WorkflowStatus.RUNNING.value
        state["resume_from"] = "planner"
        self.workflow_repository.append_hitl_action(run_id, "anchor_delay", request.model_dump(mode="json"))
        self.workflow_repository.update_run(run_id, state)

    def handle_hitl_anchor_delay(self, run_id: str, request: HitlAnchorDelayRequest) -> dict:
        self.apply_hitl_anchor_delay(run_id, request)
        self.execute_stored_run(run_id)
        return self.get_workflow(run_id)

    def apply_hitl_context_prune(self, run_id: str, request: HitlContextPruneRequest) -> None:
        state = normalize_workflow_state(self.workflow_repository.get_run_state(run_id))
        _ensure_hitl_waiting(state)
        state["graph_rag_context_tier"] = _internal_graph_rag_tier_from_product(int(request.graph_rag_context_tier))
        state["context_overflow_char_estimate"] = 0
        state["requires_hitl"] = False
        state["hitl_reason"] = ""
        state["hitl_decision_mode"] = "NONE"
        state["pending_hitl_options"] = []
        state["workflow_status"] = WorkflowStatus.RUNNING.value
        state["resume_from"] = "graph_rag"
        self.workflow_repository.append_hitl_action(run_id, "context_prune", request.model_dump(mode="json"))
        self.workflow_repository.update_run(run_id, state)

    def handle_hitl_context_prune(self, run_id: str, request: HitlContextPruneRequest) -> dict:
        self.apply_hitl_context_prune(run_id, request)
        self.execute_stored_run(run_id)
        return self.get_workflow(run_id)

    def replay_state_transaction(self, transaction_id: str) -> dict:
        transaction = self.workflow_repository.get_state_transaction(transaction_id)
        payload = deepcopy(transaction.payload)
        parsed_output = StateUpdaterOutput.model_validate(payload["state_updater_output"])

        if not transaction.graph_applied:
            self.graph_store.apply_mutations(transaction.story_id, parsed_output.mutations)
            self.workflow_repository.update_state_transaction(
                transaction_id,
                status=StateTransactionStatus.GRAPH_APPLIED,
                graph_applied=True,
                error_text="",
            )

        if not transaction.vector_applied:
            self.vector_store.add_documents(transaction.story_id, parsed_output.vector_documents)
            self.workflow_repository.update_state_transaction(
                transaction_id,
                status=StateTransactionStatus.VECTOR_APPLIED,
                vector_applied=True,
                error_text="",
            )

        if not transaction.sqlite_applied:
            self.story_repository.upsert_chapter_content(
                story_id=transaction.story_id,
                chapter_id=transaction.chapter_id,
                title=payload["chapter_title"],
                content=payload["chapter_content"],
                status="completed",
            )
            self.workflow_repository.update_state_transaction(
                transaction_id,
                status=StateTransactionStatus.SQLITE_APPLIED,
                sqlite_applied=True,
                error_text="",
            )

        final_record = self.workflow_repository.update_state_transaction(
            transaction_id,
            status=StateTransactionStatus.COMMITTED,
            error_text="",
        )
        return final_record.model_dump(mode="json")
