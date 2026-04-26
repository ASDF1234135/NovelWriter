"""Manual macro plan PUT and optional author chapter plan on run start."""

import pytest

from app.domain.schema import (
    AnchorStatus,
    EdgeMutation,
    EdgeType,
    MacroPlanPut,
    NodeMutation,
    NodeType,
    AnchorNode,
    Storyline,
    StoryCastMemberStored,
    StoryInput,
    StorylineTier,
    VolumePlan,
)
from app.repositories.sqlite.database import SQLiteDatabase
from app.repositories.sqlite.story_repository import StoryRepository
from app.repositories.sqlite.workflow_repository import WorkflowRepository
from app.services.anchor_service import AnchorService
from app.services.bible_service import BibleService
from app.services.graph_store import InMemoryGraphStore
from app.services.llm import MockLLMClient
from app.services.vector_store import InMemoryVectorStore
from app.services.workflow.service import (
    MacroPlanValidationError,
    StoryConfigurationLockedError,
    WorkflowService,
    _unachieved_from_anchor_nodes,
)


def _service(db_path: str) -> WorkflowService:
    db = SQLiteDatabase(db_path)
    return WorkflowService(
        story_repository=StoryRepository(db),
        workflow_repository=WorkflowRepository(db),
        bible_service=BibleService(),
        anchor_service=AnchorService(),
        graph_store=InMemoryGraphStore(),
        vector_store=InMemoryVectorStore(),
        llm_client=MockLLMClient(),
    )


def _macro_to_put(macro: dict) -> MacroPlanPut:
    return MacroPlanPut(
        bible=dict(macro.get("bible") or {}),
        volumes=[VolumePlan.model_validate(v) for v in macro["volumes"]],
        storylines=[Storyline.model_validate(s) for s in macro.get("storylines") or []],
        anchor_nodes=[AnchorNode.model_validate(a) for a in macro["anchor_nodes"]],
        cast=[StoryCastMemberStored.model_validate(c) for c in macro["cast"]],
        protagonist_character_id=(macro.get("protagonist_character_id") or "").strip() or None,
    )


def test_put_macro_plan_edits_volume_title(tmp_path) -> None:
    svc = _service(str(tmp_path / "put.sqlite3"))
    sid = svc.create_story(
        StoryInput(title="T", premise="p", bible={}, target_total_words=30_000),
    )["story_id"]
    macro = svc.macro_compile(sid)
    body = _macro_to_put(macro)
    new_vol = body.volumes[0].model_copy(update={"title": "手改卷名"})
    new_body = body.model_copy(update={"volumes": [new_vol, *body.volumes[1:]]})
    out = svc.put_macro_plan(sid, new_body)
    assert out["volumes"][0]["title"] == "手改卷名"


def test_put_macro_plan_locked_after_workflow_run(tmp_path) -> None:
    svc = _service(str(tmp_path / "lock.sqlite3"))
    sid = svc.create_story(
        StoryInput(title="T", premise="p", bible={}, target_total_words=30_000),
    )["story_id"]
    macro = svc.macro_compile(sid)
    body = _macro_to_put(macro)
    svc.workflow_repository.create_run(sid, 1, {"story_id": sid, "chapter_id": 1})
    with pytest.raises(StoryConfigurationLockedError):
        svc.put_macro_plan(sid, body)


def test_put_macro_plan_validates_anchor_volume(tmp_path) -> None:
    svc = _service(str(tmp_path / "bad.sqlite3"))
    sid = svc.create_story(
        StoryInput(title="T", premise="p", bible={}, target_total_words=30_000),
    )["story_id"]
    macro = svc.macro_compile(sid)
    body = _macro_to_put(macro)
    bad_anchor = body.anchor_nodes[0].model_copy(update={"volume_id": "no_such_vol"})
    bad_body = body.model_copy(update={"anchor_nodes": [bad_anchor, *body.anchor_nodes[1:]]})
    with pytest.raises(MacroPlanValidationError):
        svc.put_macro_plan(sid, bad_body)


def test_macro_compile_clears_imported_foreign_cast_ids(tmp_path) -> None:
    svc = _service(str(tmp_path / "foreign_cast.sqlite3"))
    sid = svc.create_story(
        StoryInput(title="T", premise="p", bible={}, target_total_words=30_000),
    )["story_id"]
    macro = svc.macro_compile(sid)
    body = _macro_to_put(macro)
    foreign_cast = body.cast[0].model_copy(update={"node_id": "story_old_mc_77", "canonical_name": "舊主角"})
    put_body = body.model_copy(
        update={
            "cast": [foreign_cast, *body.cast[1:]],
            "protagonist_character_id": "story_old_mc_77",
        }
    )
    svc.put_macro_plan(sid, put_body)

    assert "story_old_mc_77" in svc.graph_store.story_nodes[sid]
    svc.macro_compile(sid)

    assert "story_old_mc_77" not in svc.graph_store.story_nodes[sid]


def test_macro_compile_removes_non_cast_character_nodes_and_edges(tmp_path) -> None:
    svc = _service(str(tmp_path / "stale_character.sqlite3"))
    sid = svc.create_story(
        StoryInput(title="T", premise="p", bible={}, target_total_words=30_000),
    )["story_id"]
    macro = svc.macro_compile(sid)
    stale_character_id = "legacy_orphan_character"
    stale_edge_id = "legacy_orphan_edge"
    first_cast_id = macro["cast"][0]["node_id"]

    svc.graph_store.apply_mutations(
        sid,
        [
            NodeMutation(
                action="CREATE_NODE",
                node_id=stale_character_id,
                node_type=NodeType.CHARACTER,
                properties={
                    "canonical_name": "舊角色",
                    "description": "舊流程遺留",
                    "aliases": [],
                    "is_alive": True,
                },
            ),
            EdgeMutation(
                action="CREATE_EDGE",
                edge_id=stale_edge_id,
                source_id=stale_character_id,
                relation_type=EdgeType.HAS_RELATION,
                target_id=first_cast_id,
                attributes={
                    "valid_epoch": "epoch_present",
                    "start_event_id": "event_seed",
                    "is_truth": True,
                    "is_public": True,
                },
            ),
        ],
    )

    svc.macro_compile(sid)
    graph = svc.graph_store.dump_story_graph(sid)
    node_ids = {node.node_id for node in graph.nodes}
    edge_ids = {edge.edge_id for edge in graph.edges}
    latest_cast_ids = {member["node_id"] for member in svc.get_macro_snapshot(sid)["cast"]}

    assert stale_character_id not in node_ids
    assert stale_edge_id not in edge_ids
    assert "char_public_observer" in node_ids
    assert latest_cast_ids.issubset(node_ids)


def test_start_run_chapter_author_plan_in_state(tmp_path) -> None:
    svc = _service(str(tmp_path / "plan.sqlite3"))
    sid = svc.create_story(
        StoryInput(title="T", premise="p", bible={}, target_total_words=30_000),
    )["story_id"]
    svc.macro_compile(sid)
    wf = svc.start_run_chapter(sid, 1, author_chapter_plan="  本章著重伏筆  ")
    assert wf["state"]["author_chapter_plan"] == "本章著重伏筆"
    assert wf["state"]["chapter_outline"] == "本章著重伏筆"


def test_start_run_chapter_author_plan_truncated(tmp_path) -> None:
    svc = _service(str(tmp_path / "long.sqlite3"))
    sid = svc.create_story(
        StoryInput(title="T", premise="p", bible={}, target_total_words=30_000),
    )["story_id"]
    svc.macro_compile(sid)
    long_text = "x" * 5000
    wf = svc.start_run_chapter(sid, 1, author_chapter_plan=long_text)
    assert len(wf["state"]["author_chapter_plan"]) == 2000
    assert len(wf["state"]["chapter_outline"]) == 2000


def test_start_run_chapter_ai_freedom_and_outline_binding(tmp_path) -> None:
    svc = _service(str(tmp_path / "freedom.sqlite3"))
    sid = svc.create_story(
        StoryInput(title="T", premise="p", bible={}, target_total_words=30_000),
    )["story_id"]
    svc.macro_compile(sid)
    wf = svc.start_run_chapter(
        sid,
        1,
        chapter_outline="短",
        ai_freedom_level="strict",
    )
    assert wf["state"]["ai_freedom_level"] == "strict"
    assert wf["state"]["outline_binding_mode"] == "PARTIAL"
    assert wf["state"].get("director_state_brief") == ""

    long_outline = "章" * 100
    wf2 = svc.start_run_chapter(sid, 1, chapter_outline=long_outline, ai_freedom_level="wild")
    assert wf2["state"]["ai_freedom_level"] == "wild"
    assert wf2["state"]["outline_binding_mode"] == "FULL"

    wf3 = svc.start_run_chapter(sid, 1, ai_freedom_level="not_a_level")
    assert wf3["state"]["ai_freedom_level"] == "balanced"


def test_put_macro_plan_repairs_cross_volume_main_spine(tmp_path) -> None:
    svc = _service(str(tmp_path / "cross_vol_repair.sqlite3"))
    sid = svc.create_story(
        StoryInput(title="T", premise="p", bible={}, target_total_words=30_000),
    )["story_id"]
    v1 = f"{sid}_vol1"
    v2 = f"{sid}_vol2"
    main_sid = f"{sid}_main"
    put = MacroPlanPut(
        bible={},
        volumes=[
            VolumePlan(volume_id=v1, title="V1", summary="s", chapter_start=1, chapter_end=3),
            VolumePlan(volume_id=v2, title="V2", summary="s", chapter_start=4, chapter_end=8),
        ],
        storylines=[
            Storyline(id=main_sid, type=StorylineTier.MAIN, title="Main", overall_goal="goal", involved_entities=[]),
        ],
        anchor_nodes=[
            AnchorNode(
                id=f"{sid}_a1",
                volume_id=v1,
                storyline_ids=[main_sid],
                title="t1",
                description="d1",
                depends_on=[],
                status=AnchorStatus.UNLOCKED,
            ),
            AnchorNode(
                id=f"{sid}_a2",
                volume_id=v2,
                storyline_ids=[main_sid],
                title="t2",
                description="d2",
                depends_on=[],
                status=AnchorStatus.UNLOCKED,
            ),
        ],
        cast=[
            StoryCastMemberStored(
                node_id=f"{sid}_mc",
                canonical_name="Hero",
                role="protagonist",
            ),
        ],
        protagonist_character_id=f"{sid}_mc",
    )
    out = svc.put_macro_plan(sid, put)
    nodes = {n["id"]: n for n in out["anchor_nodes"]}
    assert f"{sid}_a1" in nodes[f"{sid}_a2"]["depends_on"]


def test_unachieved_anchor_nodes_respects_dependency_order() -> None:
    story_row = {
        "bible_json": {
            "anchor_nodes": [
                {
                    "id": "child",
                    "title": "B",
                    "description": "",
                    "status": "UNLOCKED",
                    "depends_on": ["parent"],
                    "estimated_chapter": 5,
                },
                {
                    "id": "parent",
                    "title": "A",
                    "description": "",
                    "status": "UNLOCKED",
                    "depends_on": [],
                    "estimated_chapter": 2,
                },
            ]
        }
    }
    rows = _unachieved_from_anchor_nodes(story_row, chapter_id=1)
    assert [r["anchor_id"] for r in rows] == ["parent", "child"]
