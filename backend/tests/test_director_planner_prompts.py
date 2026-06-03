from app.domain.schema import ChapterType
from app.domain.state import SafePlannerPayload
from app.services.workflow.nodes.director import _build_director_prompt, normalize_director_output
from app.services.workflow.nodes.planner import _build_planner_prompt


def test_normalize_director_output_plot_driven_when_no_b_story_directive() -> None:
    state = {}
    raw = {"chapter_type": "PLOT_DRIVEN", "b_story_directive": "", "new_elements_to_introduce": []}
    out = normalize_director_output(state, raw)
    assert out["chapter_type"] == ChapterType.PLOT_DRIVEN.value


def test_director_prompt_includes_story_premise_volume_summary_and_anchor_description() -> None:
    prompt = _build_director_prompt(
        state={
            "chapter_id": 1,
            "anchor_nodes": [
                {"id": "anchor_01", "title": "主角被迫踏上旅程", "depends_on": []},
                {"id": "anchor_02", "title": "下一錨點", "depends_on": []},
            ],
            "anchor_candidates": ["anchor_01", "anchor_02"],
            "resolved_anchors": [],
        },
        story={
            "title": "王都疑雲",
            "premise": "一名被流放的年輕騎士回到王都，追查皇室命案背後的真正凶手。",
        },
        next_anchor={
            "anchor_id": "anchor_01",
            "title": "主角被迫踏上旅程",
            "description": "主角離開原本安穩場域，正式捲入主線。",
        },
        bible_context="世界規則：皇室血脈涉及禁忌契約。",
        previous_outline="上一章主角收到密信後返城。",
    )

    assert "## Story Core" in prompt
    assert "story_premise: 一名被流放的年輕騎士回到王都，追查皇室命案背後的真正凶手。" in prompt
    assert "current_anchor_description: 主角離開原本安穩場域，正式捲入主線。" in prompt
    assert "visible_unachieved_anchors" in prompt
    assert "anchor_01" in prompt
    assert "bible_context:" in prompt
    assert "世界規則：皇室血脈涉及禁忌契約。" in prompt
    assert "Choose selected_anchor_ids with 1-2 anchor ids for this chapter." in prompt
    assert "Choose next_anchor_ids with 1-2 reachable unresolved ids for the next chapter." in prompt


def test_director_prompt_includes_previous_chapter_tail_excerpt() -> None:
    prompt = _build_director_prompt(
        state={
            "chapter_id": 1,
            "anchor_nodes": [{"id": "anchor_01", "title": "主角被迫踏上旅程", "depends_on": []}],
            "anchor_candidates": ["anchor_01"],
            "resolved_anchors": [],
        },
        story={"title": "王都疑雲", "premise": "一名被流放的年輕騎士回到王都。"},
        next_anchor={"anchor_id": "anchor_01", "title": "主角被迫踏上旅程", "description": "主角離開原本安穩場域，正式捲入主線。"},
        bible_context="世界規則：皇室血脈涉及禁忌契約。",
        previous_outline="上一章最後一段：主角仍停在轉角喘息。",
    )
    assert "previous_chapter_outline" in prompt
    assert "上一章最後一段：主角仍停在轉角喘息。" in prompt


def test_normalize_director_output_fallback_excludes_checkpoint_and_ending() -> None:
    state = {
        "chapter_id": 12,
        "trace_id": "trace-director-fallback",
        "anchor_candidates": ["cp_1", "ending_1", "n2", "n1"],
        "resolved_anchors": [],
        "anchor_nodes": [
            {"id": "n1", "depends_on": [], "node_kind": "NORMAL", "title": "N1"},
            {"id": "n2", "depends_on": [], "node_kind": "NORMAL", "title": "N2"},
            {"id": "cp_1", "depends_on": [], "node_kind": "CHECKPOINT", "title": "CP"},
            {"id": "ending_1", "depends_on": [], "node_kind": "ENDING", "title": "The ending"},
        ],
    }
    out = normalize_director_output(state, {"selected_anchor_ids": [], "next_anchor_ids": []})
    assert all(x in {"n1", "n2"} for x in out["next_anchor_ids"])


def test_director_prompt_mentions_plot_progression_smoothness() -> None:
    prompt = _build_director_prompt(
        state={"chapter_id": 3, "anchor_nodes": [], "anchor_candidates": [], "resolved_anchors": []},
        story={"title": "王都疑雲", "premise": "主角追查命案。"},
        next_anchor={"anchor_id": "anchor_01", "title": "前進", "description": "推進"},
        bible_context="世界規則",
        previous_outline="上一章摘要",
    )
    assert "Prioritize smooth plot progression when selecting anchors" in prompt


def test_director_prompt_includes_milestones_recent3_and_global_top3() -> None:
    prompt = _build_director_prompt(
        state={
            "chapter_id": 10,
            "anchor_nodes": [{"id": "anchor_01", "title": "主角被迫踏上旅程", "depends_on": []}],
            "anchor_candidates": ["anchor_01"],
            "resolved_anchors": [],
        },
        story={"title": "王都疑雲", "premise": "一名被流放的年輕騎士回到王都。"},
        next_anchor={"anchor_id": "anchor_01", "title": "主角被迫踏上旅程", "description": "主角離開原本安穩場域，正式捲入主線。"},
        bible_context="世界規則：皇室血脈涉及禁忌契約。",
        previous_outline="第9章事件推進",
    )

    assert "## Inputs You Must Use" in prompt
    assert "previous_chapter_outline: 第9章事件推進" in prompt


def test_planner_prompt_includes_story_premise_volume_summary_and_anchor_description() -> None:
    prompt = _build_planner_prompt(
        SafePlannerPayload(
            active_epoch_id="epoch_present",
            pov_character_id="char_public_observer",
            narrative_directive="推進劇情",
            selected_anchor_ids=["anchor_01"],
            story_premise="一名被流放的年輕騎士回到王都，追查皇室命案背後的真正凶手。",
            current_volume_title="卷一：命運啟動",
            current_volume_summary="建立世界與主角困境，鋪設核心衝突。",
            current_anchor_title="主角被迫踏上旅程",
            current_anchor_description="主角離開原本安穩場域，正式捲入主線。",
            ready_anchor_candidates=[
                {"anchor_id": "anchor_01", "title": "主角被迫踏上旅程"},
            ],
            blocked_anchor_candidates=[],
            graph_context="{}",
            vector_context="{}",
            bible_context="{}",
            previous_chapter_summary="上一章主角收到密信。",
            recent_chapter_context="第1章：主角收到密信並返城。",
            last_known_location="王都南門。",
            previous_attempt_ground_truth_events=[
                {"event_id": "evt_01", "description": "主角收到密信", "caused_by_event_id": None}
            ],
            previous_attempt_narrative_script="主角收到密信後準備返城。",
            continuity_notes=["灰鴉的警告尚未處理。"],
            recent_entity_names=["Kaelen", "灰鴉"],
            prior_feedback=[],
            default_chapter_words=2500,
            chapter_word_min=800,
            chapter_word_max=12000,
            lore_mysteries_progression=[{"mystery_id": "noah_memory_001", "pending_stages": [{"stage": 3, "content": "看清追殺者的臉"}]}],
            ending_vibe_cooldown_constraint={"active": True, "required_vibe": "ACTION_CLIFFHANGER"},
            general_world_lore="短句優先\n避免過度抒情",
        )
    )

    assert "## Word budget and chapter scope (required)" in prompt
    assert "target_word_count" in prompt
    assert "800 ~ 12000" in prompt
    assert "## Continuity context" in prompt
    assert "## Chapter narrative direction" in prompt
    assert "- story_premise: 一名被流放的年輕騎士回到王都，追查皇室命案背後的真正凶手。" in prompt
    assert "- active_epoch: epoch_present" in prompt
    assert "- pov_character: char_public_observer" in prompt
    assert "- current_volume_summary: 建立世界與主角困境，鋪設核心衝突。" in prompt
    assert "- current_anchor_description: 主角離開原本安穩場域，正式捲入主線。" in prompt
    assert "ready_anchor_candidates" in prompt
    assert "anchor_01" in prompt
    assert "- vector_context: {}" in prompt
    assert "- previous_chapter_summary: 上一章主角收到密信。" in prompt
    assert "- last_known_location: 王都南門。" in prompt
    assert "## Prior plan attempt (for revision)" in prompt
    assert "previous_attempt_ground_truth_events" in prompt
    assert "主角收到密信後準備返城。" in prompt
    assert "- continuity_notes: ['灰鴉的警告尚未處理。']" in prompt
    assert "- recent_entities: ['Kaelen', '灰鴉']" in prompt
    assert "- prior_feedback: []" in prompt
    assert "If previous_attempt_ground_truth_events or previous_attempt_narrative_script is present" in prompt
    assert "keep sound event chains and chapter direction" in prompt
    assert "Each ground_truth_events row must encode a new state change for this chapter" in prompt
    assert "Event granularity (hard)" in prompt
    assert "default-merge continuous fights or continuous dialogue into one macro EVENT" in prompt
    assert "Do not repackage completed trades, discoveries, dialogues, or conflicts" in prompt
    assert "author_goal" in prompt
    assert "must_include_beats" in prompt
    assert "reader_visible_facts" in prompt
    assert "reader_unresolved_questions" in prompt
    assert "private_facts_or_secret_actions" in prompt
    assert "chapter_start_location" in prompt
    assert "chapter_end_location_hint" in prompt
    assert "ending_boundary_rule" in prompt
    assert "Spatial/boundary consistency (hard)" in prompt
    assert "mandatory: true" in prompt
    assert "Never require the Author to stage entity contact or scenes that belong after the boundary" in prompt
    assert "forbidden_next_scene_actions" in prompt
    assert "forbidden_reveals" in prompt
    assert "author_safe_continuity_notes" in prompt
    assert "do not paste them verbatim to the author" in prompt
    assert "lore_mysteries_progression" in prompt
    assert "ending_vibe_cooldown_constraint" in prompt
    assert "World/craft rules are in bible_context" in prompt
    assert "New important-entity quota: 0 by default" in prompt
    assert "At most 2 nodes" in prompt


def test_planner_prompt_includes_previous_chapter_tail_excerpt() -> None:
    prompt = _build_planner_prompt(
        SafePlannerPayload(
            active_epoch_id="epoch_present",
            pov_character_id="char_public_observer",
            narrative_directive="推進劇情",
            target_anchor_id="anchor_01",
            story_premise="一名被流放的年輕騎士回到王都，追查命案。",
            current_volume_title="卷一：命運啟動",
            current_volume_summary="建立世界與主角困境，鋪設核心衝突。",
            current_anchor_title="主角被迫踏上旅程",
            current_anchor_description="主角離開原本安穩場域，正式捲入主線。",
            upcoming_unachieved_anchors=[{"anchor_id": "anchor_01", "title": "主角被迫踏上旅程", "chapter_target": 6}],
            graph_context="{}",
            vector_context="{}",
            bible_context="{}",
            previous_chapter_summary="上一章主角收到密信。",
            previous_chapter_tail_excerpt="上一章最後一段：呼吸仍未平穩，腳步卻已往前。",
            recent_chapter_context="第1章：主角收到密信。",
            last_known_location="王都南門。",
            previous_attempt_ground_truth_events=[],
            previous_attempt_narrative_script="",
            continuity_notes=[],
            recent_entity_names=[],
            prior_feedback=[],
            default_chapter_words=2500,
            chapter_word_min=800,
            chapter_word_max=12000,
        )
    )
    assert "previous_chapter_tail_excerpt" in prompt
    assert "呼吸仍未平穩" in prompt
