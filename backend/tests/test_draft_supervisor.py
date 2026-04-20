from app.domain.schema import DraftSupervisorOutput, LengthAdjustment, SuggestionType, ViolationType
from app.services.anchor_service import AnchorService
from app.services.bible_service import BibleService
from app.services.llm import LLMResult, MockLLMClient
from app.services.vector_store import InMemoryVectorStore
from app.services.workflow.context import WorkflowContext
from app.services.workflow.nodes.draft_supervisor import run_draft_supervisor
from app.repositories.sqlite.database import SQLiteDatabase
from app.repositories.sqlite.story_repository import StoryRepository
from app.repositories.sqlite.workflow_repository import WorkflowRepository
from app.services.graph_store import InMemoryGraphStore


class _StubDraftJsonLLM:
    def invoke(self, prompt: str) -> LLMResult:
        return LLMResult(content="{}", token_usage=1, latency_ms=1)

    def invoke_text(self, prompt: str, profile) -> LLMResult:
        return LLMResult(content="{}", token_usage=1, latency_ms=1)

    def invoke_json(self, prompt, response_model, profile):
        fixed = DraftSupervisorOutput(
            is_approved=False,
            violation_type=[ViolationType.INCONSISTENCY],
            suggestion_type=SuggestionType.REWRITE,
            feedback_to_agent="",
            length_adjustment=LengthAdjustment.NONE,
        )
        return fixed, LLMResult(content="{}", token_usage=1, latency_ms=1)


class _StubApproveJsonLLM:
    def invoke(self, prompt: str) -> LLMResult:
        return LLMResult(content="{}", token_usage=1, latency_ms=1)

    def invoke_text(self, prompt: str, profile) -> LLMResult:
        return LLMResult(content="{}", token_usage=1, latency_ms=1)

    def invoke_json(self, prompt, response_model, profile):
        fixed = DraftSupervisorOutput(
            is_approved=True,
            violation_type=[ViolationType.NONE],
            suggestion_type=SuggestionType.NONE,
            feedback_to_agent="",
            length_adjustment=LengthAdjustment.NONE,
        )
        return fixed, LLMResult(content="{}", token_usage=1, latency_ms=1)


def test_draft_supervisor_uses_normalized_length_for_word_count(tmp_path) -> None:
    db = SQLiteDatabase(str(tmp_path / "draft_supervisor.sqlite3"))
    context = WorkflowContext(
        story_repository=StoryRepository(db),
        workflow_repository=WorkflowRepository(db),
        bible_service=BibleService(),
        anchor_service=AnchorService(),
        graph_store=InMemoryGraphStore(),
        vector_store=InMemoryVectorStore(),
        llm_client=MockLLMClient(),
        run_id="run-draft-supervisor",
    )
    state = {
        "chapter_id": 1,
        "active_epoch_id": "epoch_present",
        "target_anchor_id": "anchor_01",
        "unachieved_anchors": [],
        "target_word_count": 4,
        "story_output_language": "zh-Hant",
        "ground_truth_events": [],
        "narrative_script": "",
        "ending_boundary_rule": "",
        "forbidden_next_scene_actions": [],
        "current_draft": "甲!!!",
        "graph_context": "{}",
        "vector_context": "{}",
        "bible_context": "{}",
    }

    output, masked = run_draft_supervisor(state, context)

    assert output["is_approved"] is False
    assert "WORD_COUNT_UNMATCH" in output["violation_type"]
    assert masked["normalized_current_draft_length"] == 1
    assert output["length_adjustment"] == "EXPAND"


def test_draft_supervisor_en_uses_word_count_not_letter_count(tmp_path) -> None:
    db = SQLiteDatabase(str(tmp_path / "draft_supervisor_en_words.sqlite3"))
    context = WorkflowContext(
        story_repository=StoryRepository(db),
        workflow_repository=WorkflowRepository(db),
        bible_service=BibleService(),
        anchor_service=AnchorService(),
        graph_store=InMemoryGraphStore(),
        vector_store=InMemoryVectorStore(),
        llm_client=MockLLMClient(),
        run_id="run-draft-supervisor-en",
    )
    state = {
        "chapter_id": 1,
        "active_epoch_id": "epoch_present",
        "target_anchor_id": "anchor_01",
        "unachieved_anchors": [],
        "story_output_language": "en",
        "target_word_count": 20,
        "normalized_length_min": 13,
        "normalized_length_max": 27,
        "ground_truth_events": [],
        "narrative_script": "",
        "ending_boundary_rule": "",
        "forbidden_next_scene_actions": [],
        "current_draft": "one two three four five",
        "graph_context": "{}",
        "vector_context": "{}",
        "bible_context": "{}",
    }

    output, masked = run_draft_supervisor(state, context)

    assert output["is_approved"] is False
    assert "WORD_COUNT_UNMATCH" in output["violation_type"]
    assert masked["normalized_current_draft_length"] == 5
    assert output["length_adjustment"] == "EXPAND"


def test_draft_supervisor_does_not_use_python_boundary_substring_gate(tmp_path) -> None:
    """Regression: english forbidden lines used to false-positive via token substring matching (the/not/for...)."""
    db = SQLiteDatabase(str(tmp_path / "draft_supervisor_boundary.sqlite3"))
    context = WorkflowContext(
        story_repository=StoryRepository(db),
        workflow_repository=WorkflowRepository(db),
        bible_service=BibleService(),
        anchor_service=AnchorService(),
        graph_store=InMemoryGraphStore(),
        vector_store=InMemoryVectorStore(),
        llm_client=_StubApproveJsonLLM(),
        run_id="run-draft-supervisor-boundary",
    )
    draft = (
        "The protagonist waits at the door, not entering. "
        "For now, the scene holds on breath and footsteps. "
        "They do not move into a new location."
    )
    state = {
        "chapter_id": 1,
        "active_epoch_id": "epoch_present",
        "target_anchor_id": "anchor_01",
        "unachieved_anchors": [],
        "target_word_count": 120,
        "ground_truth_events": [],
        "narrative_script": "",
        "ending_boundary_rule": "Stop before entering the safe house interior.",
        "forbidden_next_scene_actions": [
            "Do not move into a new scene or new location after the chapter's effective end position.",
            "Do not resolve a hanging thread early, or complete meetings meant for the next chapter.",
        ],
        "current_draft": draft,
        "graph_context": "{}",
        "vector_context": "{}",
        "bible_context": "{}",
    }

    output, _masked = run_draft_supervisor(state, context)
    assert output["is_approved"] is True


def test_draft_supervisor_uses_35_percent_tolerance_window(tmp_path) -> None:
    db = SQLiteDatabase(str(tmp_path / "draft_supervisor_tolerance.sqlite3"))
    context = WorkflowContext(
        story_repository=StoryRepository(db),
        workflow_repository=WorkflowRepository(db),
        bible_service=BibleService(),
        anchor_service=AnchorService(),
        graph_store=InMemoryGraphStore(),
        vector_store=InMemoryVectorStore(),
        llm_client=MockLLMClient(),
        run_id="run-draft-supervisor-tolerance",
    )
    state = {
        "chapter_id": 1,
        "active_epoch_id": "epoch_present",
        "target_anchor_id": "anchor_01",
        "unachieved_anchors": [],
        "target_word_count": 100,
        "ground_truth_events": [],
        "narrative_script": "",
        "ending_boundary_rule": "",
        "forbidden_next_scene_actions": [],
        "current_draft": "甲" * 66,
        "graph_context": "{}",
        "vector_context": "{}",
        "bible_context": "{}",
    }

    output, _ = run_draft_supervisor(state, context)

    assert output["is_approved"] is True
    assert output["length_adjustment"] == "NONE"


def test_draft_supervisor_marks_compress_when_over_limit(tmp_path) -> None:
    db = SQLiteDatabase(str(tmp_path / "draft_supervisor_compress.sqlite3"))
    context = WorkflowContext(
        story_repository=StoryRepository(db),
        workflow_repository=WorkflowRepository(db),
        bible_service=BibleService(),
        anchor_service=AnchorService(),
        graph_store=InMemoryGraphStore(),
        vector_store=InMemoryVectorStore(),
        llm_client=MockLLMClient(),
        run_id="run-draft-supervisor-compress",
    )
    state = {
        "chapter_id": 1,
        "active_epoch_id": "epoch_present",
        "target_anchor_id": "anchor_01",
        "unachieved_anchors": [],
        "target_word_count": 100,
        "ground_truth_events": [],
        "narrative_script": "",
        "ending_boundary_rule": "",
        "forbidden_next_scene_actions": [],
        "current_draft": "甲" * 140,
        "graph_context": "{}",
        "vector_context": "{}",
        "bible_context": "{}",
    }

    output, _ = run_draft_supervisor(state, context)

    assert output["is_approved"] is False
    assert "WORD_COUNT_UNMATCH" in output["violation_type"]
    assert output["length_adjustment"] == "COMPRESS"


def test_draft_supervisor_appends_deterministic_feedback_when_llm_critique_empty(tmp_path) -> None:
    db = SQLiteDatabase(str(tmp_path / "draft_supervisor_stub.sqlite3"))
    context = WorkflowContext(
        story_repository=StoryRepository(db),
        workflow_repository=WorkflowRepository(db),
        bible_service=BibleService(),
        anchor_service=AnchorService(),
        graph_store=InMemoryGraphStore(),
        vector_store=InMemoryVectorStore(),
        llm_client=_StubDraftJsonLLM(),
        run_id="run-draft-stub",
    )
    state = {
        "chapter_id": 1,
        "active_epoch_id": "epoch_present",
        "target_anchor_id": "anchor_01",
        "unachieved_anchors": [],
        "target_word_count": 100,
        "ground_truth_events": [],
        "narrative_script": "",
        "ending_boundary_rule": "",
        "forbidden_next_scene_actions": [],
        "planned_graph_nodes": [],
        "current_draft": "甲" * 66,
        "graph_context": "{}",
        "vector_context": "{}",
        "bible_context": "{}",
    }

    output, _ = run_draft_supervisor(state, context)

    assert output["is_approved"] is False
    fb = output["feedback_to_agent"]
    assert "(system)" in fb.casefold()
    assert "narrative_script" in fb.casefold()
    assert "ending_boundary_rule" not in fb.casefold()


def test_draft_supervisor_feedback_fill_no_boundary_boilerplate_with_rule_set(tmp_path) -> None:
    """INCONSISTENCY fallback must not paste boundary field names when chapter did not cross the gate."""
    db = SQLiteDatabase(str(tmp_path / "draft_supervisor_fill.sqlite3"))
    context = WorkflowContext(
        story_repository=StoryRepository(db),
        workflow_repository=WorkflowRepository(db),
        bible_service=BibleService(),
        anchor_service=AnchorService(),
        graph_store=InMemoryGraphStore(),
        vector_store=InMemoryVectorStore(),
        llm_client=_StubDraftJsonLLM(),
        run_id="run-draft-stub-fill",
    )
    state = {
        "chapter_id": 1,
        "active_epoch_id": "epoch_present",
        "target_anchor_id": "anchor_01",
        "unachieved_anchors": [],
        "target_word_count": 100,
        "ground_truth_events": [],
        "narrative_script": "",
        "chapter_start_location": "",
        "chapter_end_location_hint": "巷口。",
        "ending_boundary_rule": "本章最遠只能停在巷口，不可進入基地內部。",
        "forbidden_next_scene_actions": ["不可進入基地內部"],
        "must_include_beats": [],
        "planned_graph_nodes": [],
        "current_draft": "甲" * 66,
        "graph_context": "{}",
        "vector_context": "{}",
        "bible_context": "{}",
    }

    output, _ = run_draft_supervisor(state, context)

    assert output["is_approved"] is False
    fb = output["feedback_to_agent"].casefold()
    assert "ending_boundary_rule" not in fb
    assert "forbidden_next_scene_actions" not in fb


def test_draft_supervisor_rejects_jargon_overuse(tmp_path) -> None:
    db = SQLiteDatabase(str(tmp_path / "draft_supervisor_jargon.sqlite3"))
    context = WorkflowContext(
        story_repository=StoryRepository(db),
        workflow_repository=WorkflowRepository(db),
        bible_service=BibleService(),
        anchor_service=AnchorService(),
        graph_store=InMemoryGraphStore(),
        vector_store=InMemoryVectorStore(),
        llm_client=MockLLMClient(),
        run_id="run-draft-supervisor-jargon",
    )
    state = {
        "chapter_id": 1,
        "active_epoch_id": "epoch_present",
        "target_anchor_id": "anchor_01",
        "unachieved_anchors": [],
        "target_word_count": 120,
        "ground_truth_events": [],
        "narrative_script": "主角在現場辨識到異常，並確認風險仍在。",
        "ending_boundary_rule": "",
        "forbidden_next_scene_actions": [],
        "current_draft": "他啟動了「獵犬協同邏輯」，接著切換到「策略性緩衝節點：二級」。",
        "graph_context": "{}",
        "vector_context": "{}",
        "bible_context": "{}",
    }

    output, _ = run_draft_supervisor(state, context)

    assert output["is_approved"] is False
    assert "INCONSISTENCY" in output["violation_type"]
    assert "disposable proper nouns" in output["feedback_to_agent"].casefold()


def test_draft_supervisor_blocks_unapproved_identity_reveal(tmp_path) -> None:
    db = SQLiteDatabase(str(tmp_path / "draft_supervisor_identity.sqlite3"))
    context = WorkflowContext(
        story_repository=StoryRepository(db),
        workflow_repository=WorkflowRepository(db),
        bible_service=BibleService(),
        anchor_service=AnchorService(),
        graph_store=InMemoryGraphStore(),
        vector_store=InMemoryVectorStore(),
        llm_client=MockLLMClient(),
        run_id="run-draft-supervisor-identity",
    )
    state = {
        "chapter_id": 1,
        "active_epoch_id": "epoch_present",
        "target_anchor_id": "anchor_01",
        "unachieved_anchors": [],
        "target_word_count": 120,
        "ground_truth_events": [],
        "narrative_script": "主角只應該懷疑，不可確認真身分。",
        "ending_boundary_rule": "",
        "forbidden_next_scene_actions": [],
        "forbidden_reveals": ["不要揭露「夜鴉」的真身分"],
        "current_draft": "主角終於確定線人就是夜鴉。",
        "graph_context": "{}",
        "vector_context": "{}",
        "bible_context": "{}",
    }

    output, _ = run_draft_supervisor(state, context)

    assert output["is_approved"] is False
    assert "POV_LEAK" in output["violation_type"]
    assert "identity reveals not allowed" in output["feedback_to_agent"].casefold()


def test_draft_supervisor_allows_identity_reveal_from_allowlist(tmp_path) -> None:
    db = SQLiteDatabase(str(tmp_path / "draft_supervisor_identity_allow.sqlite3"))
    context = WorkflowContext(
        story_repository=StoryRepository(db),
        workflow_repository=WorkflowRepository(db),
        bible_service=BibleService(),
        anchor_service=AnchorService(),
        graph_store=InMemoryGraphStore(),
        vector_store=InMemoryVectorStore(),
        llm_client=MockLLMClient(),
        run_id="run-draft-supervisor-identity-allow",
    )
    state = {
        "chapter_id": 1,
        "active_epoch_id": "epoch_present",
        "target_anchor_id": "anchor_01",
        "unachieved_anchors": [],
        "target_word_count": 120,
        "ground_truth_events": [],
        "narrative_script": "主角可以在此章確認夜鴉真身分。",
        "ending_boundary_rule": "",
        "forbidden_next_scene_actions": [],
        "forbidden_reveals": ["不要揭露「夜鴉」的真身分"],
        "allowed_identity_reveals_this_chapter": ["夜鴉"],
        "current_draft": "主角終於確定線人就是夜鴉。",
        "graph_context": "{}",
        "vector_context": "{}",
        "bible_context": "{}",
    }

    output, _ = run_draft_supervisor(state, context)

    assert "POV_LEAK" not in output["violation_type"]


def test_draft_supervisor_does_not_flag_low_risk_memory_labels_as_identity(tmp_path) -> None:
    db = SQLiteDatabase(str(tmp_path / "draft_supervisor_identity_memory.sqlite3"))
    context = WorkflowContext(
        story_repository=StoryRepository(db),
        workflow_repository=WorkflowRepository(db),
        bible_service=BibleService(),
        anchor_service=AnchorService(),
        graph_store=InMemoryGraphStore(),
        vector_store=InMemoryVectorStore(),
        llm_client=MockLLMClient(),
        run_id="run-draft-supervisor-identity-memory",
    )
    state = {
        "chapter_id": 1,
        "active_epoch_id": "epoch_present",
        "target_anchor_id": "anchor_01",
        "unachieved_anchors": [],
        "target_word_count": 120,
        "ground_truth_events": [],
        "narrative_script": "主角應保持懷疑，不揭露真身份。",
        "ending_boundary_rule": "",
        "forbidden_next_scene_actions": [],
        "forbidden_reveals": ['Do not reveal true identity marker "Memory 001" this chapter.'],
        "current_draft": "He copied Memory 001 from the archive card and moved on.",
        "graph_context": "{}",
        "vector_context": "{}",
        "bible_context": "{}",
    }

    output, _ = run_draft_supervisor(state, context)

    assert "POV_LEAK" not in output["violation_type"]
    assert "identity reveals not allowed" not in output["feedback_to_agent"].casefold()


def test_draft_supervisor_allows_mandatory_surface_with_hyphen_space_variant(tmp_path) -> None:
    db = SQLiteDatabase(str(tmp_path / "draft_supervisor_mandatory_variant.sqlite3"))
    context = WorkflowContext(
        story_repository=StoryRepository(db),
        workflow_repository=WorkflowRepository(db),
        bible_service=BibleService(),
        anchor_service=AnchorService(),
        graph_store=InMemoryGraphStore(),
        vector_store=InMemoryVectorStore(),
        llm_client=_StubApproveJsonLLM(),
        run_id="run-draft-supervisor-mandatory-variant",
    )
    state = {
        "chapter_id": 1,
        "active_epoch_id": "epoch_present",
        "target_anchor_id": "anchor_01",
        "unachieved_anchors": [],
        "target_word_count": 120,
        "ground_truth_events": [],
        "narrative_script": "",
        "ending_boundary_rule": "",
        "forbidden_next_scene_actions": [],
        "planned_graph_nodes": [
            {
                "node_id": "item_memory_dampener",
                "node_type": "ITEM",
                "mandatory": True,
                "role": "ITEM",
                "canonical_name": "memory dampener",
                "writing_brief": "記憶阻尼器",
            }
        ],
        "author_extraction_surface_hints": [
            {"node_id": "item_memory_dampener", "surface_forms": ["memory-dampener"]}
        ],
        "current_draft": "He activated the memory dampener and waited for the hum to settle.",
        "graph_context": "{}",
        "vector_context": "{}",
        "bible_context": "{}",
    }

    output, _ = run_draft_supervisor(state, context)

    assert "MISSING_MANDATORY_ENTITY_MAPPING" not in output["violation_type"]


def test_draft_supervisor_mandatory_feedback_includes_diagnostics(tmp_path) -> None:
    db = SQLiteDatabase(str(tmp_path / "draft_supervisor_mandatory_feedback.sqlite3"))
    context = WorkflowContext(
        story_repository=StoryRepository(db),
        workflow_repository=WorkflowRepository(db),
        bible_service=BibleService(),
        anchor_service=AnchorService(),
        graph_store=InMemoryGraphStore(),
        vector_store=InMemoryVectorStore(),
        llm_client=MockLLMClient(),
        run_id="run-draft-supervisor-mandatory-feedback",
    )
    state = {
        "chapter_id": 1,
        "active_epoch_id": "epoch_present",
        "target_anchor_id": "anchor_01",
        "unachieved_anchors": [],
        "target_word_count": 120,
        "ground_truth_events": [],
        "narrative_script": "",
        "ending_boundary_rule": "",
        "forbidden_next_scene_actions": [],
        "planned_graph_nodes": [
            {
                "node_id": "item_memory_dampener",
                "node_type": "ITEM",
                "mandatory": True,
                "role": "ITEM",
                "canonical_name": "memory dampener",
                "writing_brief": "記憶阻尼器",
            }
        ],
        "author_extraction_surface_hints": [
            {"node_id": "item_memory_dampener", "surface_forms": ["memory dampener"]}
        ],
        "current_draft": "He calibrated a memory shunt before moving.",
        "graph_context": "{}",
        "vector_context": "{}",
        "bible_context": "{}",
    }

    output, _ = run_draft_supervisor(state, context)

    assert output["is_approved"] is False
    assert "MISSING_MANDATORY_ENTITY_MAPPING" in output["violation_type"]
    assert "Diagnostics:" in output["feedback_to_agent"]
    assert "item_memory_dampener" in output["feedback_to_agent"]
