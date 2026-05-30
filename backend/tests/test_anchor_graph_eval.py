from __future__ import annotations

from app.services.workflow.anchor_graph_eval import (
    CACHE_SOURCE_ANCHOR_RESOLVE,
    build_cache_from_anchor_resolution,
    build_anchor_condition_desc,
    ids_to_evaluate,
    merge_cache_into_runtime,
    partition_preflight_ids,
)


def test_ids_to_evaluate_excludes_next() -> None:
    assert ids_to_evaluate(["a1", "a2"], ["a2"]) == ["a1"]


def test_build_anchor_condition_desc_includes_description() -> None:
    desc = build_anchor_condition_desc(
        "a1",
        {"title": "T", "description": "進城並取得密信", "node_kind": "NORMAL", "depends_on": []},
    )
    assert "進城並取得密信" in desc
    assert "a1" in desc


def test_build_cache_from_anchor_resolution_only_unresolved_graph_rag() -> None:
    resolution = {
        "evidence_summary": [
            {"anchor_id": "a1", "resolved": False, "reasoning": "尚未完成", "confidence": 0.8},
            {"anchor_id": "a2", "resolved": True, "reasoning": "done", "confidence": 0.9},
            {
                "anchor_id": "a3",
                "score": 0.1,
                "decision": "UNRESOLVED",
                "decision_reason": "fallback",
            },
        ]
    }
    cache = build_cache_from_anchor_resolution(5, resolution)
    assert set(cache.keys()) == {"a1"}
    assert cache["a1"]["chapter_id"] == 5
    assert cache["a1"]["source"] == CACHE_SOURCE_ANCHOR_RESOLVE


def test_merge_cache_clears_resolved_ids() -> None:
    rt = {
        "anchor_unresolved_eval_cache": {
            "a1": {"chapter_id": 4, "resolved": False, "reasoning": "old", "source": CACHE_SOURCE_ANCHOR_RESOLVE},
            "a2": {"chapter_id": 4, "resolved": False, "reasoning": "keep", "source": CACHE_SOURCE_ANCHOR_RESOLVE},
        }
    }
    merge_cache_into_runtime(rt, {"a3": {"chapter_id": 5, "resolved": False, "reasoning": "new", "source": CACHE_SOURCE_ANCHOR_RESOLVE}}, clear_anchor_ids=["a1"])
    keys = set(rt["anchor_unresolved_eval_cache"].keys())
    assert "a1" not in keys
    assert "a2" in keys
    assert "a3" in keys


def test_partition_preflight_reuses_prev_chapter_cache() -> None:
    cache = {
        "a1": {
            "chapter_id": 5,
            "resolved": False,
            "reasoning": "上一章未達成說明",
            "source": CACHE_SOURCE_ANCHOR_RESOLVE,
        }
    }
    reuse, eval_ids = partition_preflight_ids(
        ["a1"],
        resolved_anchors=[],
        cache=cache,
        chapter_id=6,
        node_by_id={"a1": {"title": "T", "description": "d"}},
    )
    assert eval_ids == []
    assert len(reuse) == 1
    assert reuse[0]["source"] == "cache"


def test_partition_preflight_skips_stale_cache_chapter() -> None:
    cache = {
        "a1": {
            "chapter_id": 3,
            "resolved": False,
            "reasoning": "stale",
            "source": CACHE_SOURCE_ANCHOR_RESOLVE,
        }
    }
    reuse, eval_ids = partition_preflight_ids(
        ["a1"],
        resolved_anchors=[],
        cache=cache,
        chapter_id=6,
        node_by_id={"a1": {"title": "T", "description": "d"}},
    )
    assert reuse == []
    assert eval_ids == ["a1"]
