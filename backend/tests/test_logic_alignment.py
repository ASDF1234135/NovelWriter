from app.repositories.sqlite.database import SQLiteDatabase
from app.repositories.sqlite.story_repository import StoryRepository
from app.repositories.sqlite.workflow_repository import WorkflowRepository
from app.services.anchor_service import AnchorService
from app.services.bible_service import BibleService
from app.services.graph_store import InMemoryGraphStore
from app.services.llm import MockLLMClient
from app.services.vector_store import InMemoryVectorStore
from app.services.workflow.context import WorkflowContext
from app.services.workflow.nodes.logic_alignment import run_logic_alignment


def _ctx(tmp_path) -> WorkflowContext:
    # Use real context wiring like other node tests; Mock client keeps it deterministic.
    db = SQLiteDatabase(str(tmp_path / "logic_alignment.sqlite3"))
    return WorkflowContext(
        story_repository=StoryRepository(db),
        workflow_repository=WorkflowRepository(db),
        bible_service=BibleService(),
        anchor_service=AnchorService(),
        graph_store=InMemoryGraphStore(),
        vector_store=InMemoryVectorStore(),
        llm_client=MockLLMClient(),
        run_id="run-logic-alignment-test",
    )


def test_logic_alignment_no_rules_low_complexity_passes_without_hitl(tmp_path) -> None:
    state = {
        "story_id": "s1",
        "chapter_id": 1,
        "pov_character_id": "char_public_observer",
        "chapter_hard_rules": "   ",
        "narrative_script": "草稿劇本",
        "must_include_beats": ["A", "B"],
        "ground_truth_events": [{"event_id": "E1", "description": "x"}],
    }
    out, payload, tokens, latency = run_logic_alignment(state, _ctx(tmp_path))
    assert tokens == 0
    assert latency == 0
    assert out["alignment_log"].startswith("Skipped:")
    assert out["safe_chapter_rules"] == ""
    assert out["requires_hitl"] is False
    assert out["hitl_reason"] is None
    assert payload.get("skipped") is True


def test_logic_alignment_no_rules_high_complexity_requests_hitl(tmp_path) -> None:
    state = {
        "story_id": "s1",
        "chapter_id": 1,
        "pov_character_id": "char_public_observer",
        "chapter_hard_rules": "",
        "narrative_script": "他們開始俄羅斯輪盤變體，談判籌碼與回合結算後才可行動。",
        "must_include_beats": ["宣告勝利條件", "每回合判定", "失敗方承擔代價"],
        "ground_truth_events": [{"event_id": "E1", "description": "啟動博弈機制與判定流程"}],
    }
    out, payload, tokens, latency = run_logic_alignment(state, _ctx(tmp_path))
    assert tokens == 0
    assert latency == 0
    # Heuristic mind-game detection is removed; without hard rules and without canon-audit context,
    # logic_alignment skips without routing to HITL.
    assert out["requires_hitl"] is False
    assert out["hitl_reason"] is None
    assert payload.get("skipped") is True


def test_logic_alignment_mock_passthrough_with_rules(tmp_path) -> None:
    state = {
        "story_id": "s1",
        "chapter_id": 1,
        "pov_character_id": "char_public_observer",
        "chapter_hard_rules": "規則：每回合只能行動一次",
        "narrative_script": "草稿劇本",
        "must_include_beats": ["A", "B"],
        "ground_truth_events": [{"event_id": "E1", "description": "x"}],
    }
    out, _payload, tokens, _latency = run_logic_alignment(state, _ctx(tmp_path))
    assert tokens == 0
    assert out["safe_chapter_rules"] == "規則：每回合只能行動一次"
    assert "Mock:" in out["alignment_log"]
    assert out["requires_hitl"] is False
