from app.domain.schema import ChapterType
from app.domain.state import SafePlannerPayload
from app.services.workflow.nodes.director import _build_director_prompt, normalize_director_output
from app.services.workflow.nodes.planner import _build_planner_prompt


def test_normalize_director_output_world_building_when_b_story_pool_has_no_ids() -> None:
    state = {"distance_to_anchor": 3, "active_b_stories": [{"id": "", "desc": "orphan row"}]}
    raw = {"chapter_type": "PLOT_DRIVEN", "b_story_directive": "", "new_elements_to_introduce": []}
    out = normalize_director_output(state, raw)
    assert out["chapter_type"] == ChapterType.WORLD_BUILDING.value
    assert "Explore surroundings" in (out.get("b_story_directive") or "")


def test_director_prompt_includes_story_premise_volume_summary_and_anchor_description() -> None:
    prompt = _build_director_prompt(
        state={"chapter_id": 1, "graph_context": "{}"},
        story={
            "title": "王都疑雲",
            "premise": "一名被流放的年輕騎士回到王都，追查皇室命案背後的真正凶手。",
        },
        volumes=[
            {
                "title": "卷一：命運啟動",
                "summary": "建立世界與主角困境，鋪設核心衝突。",
                "chapter_start": 1,
                "chapter_end": 6,
                "target_volume_words": 18000,
            }
        ],
        next_anchor={
            "anchor_id": "anchor_01",
            "title": "主角被迫踏上旅程",
            "description": "主角離開原本安穩場域，正式捲入主線。",
        },
        visible_unachieved_anchors=[
            {"anchor_id": "anchor_01", "title": "主角被迫踏上旅程", "chapter_target": 6},
            {"anchor_id": "anchor_02", "title": "下一錨點", "chapter_target": 10},
        ],
        bible_context="世界規則：皇室血脈涉及禁忌契約。",
    )

    assert "## Story core" in prompt
    assert "story_premise: 一名被流放的年輕騎士回到王都，追查皇室命案背後的真正凶手。" in prompt
    assert "volume_summary: 建立世界與主角困境，鋪設核心衝突。" in prompt
    assert "chapter length is decided later by Planner" in prompt
    assert "current_anchor_description: 主角離開原本安穩場域，正式捲入主線。" in prompt
    assert "visible_unachieved_anchors" in prompt
    assert "anchor_01" in prompt
    assert "bible_context: 世界規則：皇室血脈涉及禁忌契約。" in prompt
    assert "Choose chapter_type (PLOT_DRIVEN / CHARACTER_DRIVEN / WORLD_BUILDING), POV, Epoch, tone, narrative_directive" in prompt
    assert "narrative_directive must name new plot advancement" in prompt
    assert "start, destination, or end-of-chapter effective position" in prompt


def test_director_prompt_includes_previous_chapter_tail_excerpt() -> None:
    prompt = _build_director_prompt(
        state={
            "chapter_id": 1,
            "graph_context": "{}",
            "previous_chapter_tail_excerpt": "上一章最後一段：主角仍停在轉角喘息。",
        },
        story={"title": "王都疑雲", "premise": "一名被流放的年輕騎士回到王都。"},
        volumes=[
            {
                "title": "卷一：命運啟動",
                "summary": "建立世界與主角困境，鋪設核心衝突。",
                "chapter_start": 1,
                "chapter_end": 6,
                "target_volume_words": 18000,
            }
        ],
        next_anchor={"anchor_id": "anchor_01", "title": "主角被迫踏上旅程", "description": "主角離開原本安穩場域，正式捲入主線。"},
        visible_unachieved_anchors=[
            {"anchor_id": "anchor_01", "title": "主角被迫踏上旅程", "chapter_target": 6},
        ],
        bible_context="世界規則：皇室血脈涉及禁忌契約。",
    )
    assert "previous_chapter_tail_excerpt" in prompt
    assert "上一章最後一段：主角仍停在轉角喘息。" in prompt


def test_director_prompt_includes_milestones_recent3_and_global_top3() -> None:
    prompt = _build_director_prompt(
        state={
            "chapter_id": 10,
            "graph_context": "{}",
            "all_milestone_summaries": [{"chapter_start": 6, "chapter_end": 10, "milestone_summary": "MS(6-10)"}],
            "recent_chapter_summaries": [
                {
                    "chapter_id": 9,
                    "plot_summary": "第9章事件推進",
                    "conflict_type": "MYSTERY",
                    "resolution_method": "DISCOVERY",
                }
            ],
            "global_conflict_type_top3": [{"conflict_type": "MYSTERY", "cnt": 4}],
            "global_resolution_method_top3": [{"resolution_method": "DISCOVERY", "cnt": 3}],
            "resolution_cooldown_constraint": {"active": True, "ban_text": "禁止重複精神對決"},
            "ending_vibe_cooldown_constraint": {"active": True, "interrupt_text": "結尾必須 ACTION_CLIFFHANGER"},
            "lore_mysteries_progression": [
                {
                    "mystery_id": "noah_memory_001",
                    "description": "諾亞失去的關鍵記憶",
                    "pending_stages": [{"stage": 3, "content": "揭露追殺者真面目"}],
                }
            ],
            "writing_note": ["短句優先", "避免過度抒情"],
        },
        story={"title": "王都疑雲", "premise": "一名被流放的年輕騎士回到王都。"},
        volumes=[
            {
                "title": "卷一：命運啟動",
                "summary": "建立世界與主角困境，鋪設核心衝突。",
                "chapter_start": 1,
                "chapter_end": 12,
                "target_volume_words": 18000,
            }
        ],
        next_anchor={"anchor_id": "anchor_01", "title": "主角被迫踏上旅程", "description": "主角離開原本安穩場域，正式捲入主線。"},
        visible_unachieved_anchors=[
            {"anchor_id": "anchor_01", "title": "主角被迫踏上旅程", "chapter_target": 12},
        ],
        bible_context="世界規則：皇室血脈涉及禁忌契約。",
    )

    assert "## Macro rhythm memory (all milestones to date)" in prompt
    assert "MS(6-10)" in prompt
    assert "## Last ~3 chapter structured summaries" in prompt
    assert "Ch.9: 第9章事件推進" in prompt
    assert "## Global trope stats (Top-3)" in prompt
    assert "MYSTERY: 4" in prompt
    assert "## System hard constraints (must obey)" in prompt
    assert "禁止重複精神對決" in prompt
    assert "ACTION_CLIFFHANGER" in prompt
    assert "## Lore mystery progression (pending stages)" in prompt
    assert "## Writing notes (global craft rules)" in prompt
    assert "短句優先" in prompt


def test_planner_prompt_includes_story_premise_volume_summary_and_anchor_description() -> None:
    prompt = _build_planner_prompt(
        SafePlannerPayload(
            active_epoch_id="epoch_present",
            pov_character_id="char_public_observer",
            narrative_directive="推進劇情",
            target_anchor_id="anchor_01",
            story_premise="一名被流放的年輕騎士回到王都，追查皇室命案背後的真正凶手。",
            current_volume_title="卷一：命運啟動",
            current_volume_summary="建立世界與主角困境，鋪設核心衝突。",
            current_anchor_title="主角被迫踏上旅程",
            current_anchor_description="主角離開原本安穩場域，正式捲入主線。",
            upcoming_unachieved_anchors=[
                {"anchor_id": "anchor_01", "title": "主角被迫踏上旅程", "chapter_target": 6},
            ],
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
            writing_note=["短句優先", "避免過度抒情"],
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
    assert "upcoming_unachieved_anchors" in prompt
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
    assert "writing_note_rules" in prompt
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
