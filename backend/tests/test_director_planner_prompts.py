from app.domain.state import SafePlannerPayload
from app.services.workflow.nodes.director import _build_director_prompt
from app.services.workflow.nodes.planner import _build_planner_prompt


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

    assert "## 故事核心" in prompt
    assert "story_premise: 一名被流放的年輕騎士回到王都，追查皇室命案背後的真正凶手。" in prompt
    assert "volume_summary: 建立世界與主角困境，鋪設核心衝突。" in prompt
    assert "本章字數由後續 Planner 決定" in prompt
    assert "current_anchor_description: 主角離開原本安穩場域，正式捲入主線。" in prompt
    assert "visible_unachieved_anchors" in prompt
    assert "anchor_01" in prompt
    assert "bible_context: 世界規則：皇室血脈涉及禁忌契約。" in prompt
    assert "請決定本章 POV、Epoch、tone 與 narrative_directive" in prompt
    assert "narrative_directive 必須明確指出本章要新增的劇情推進" in prompt
    assert "起點、目的地或章末有效位置" in prompt


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
        )
    )

    assert "## 字數與本章內容（必做）" in prompt
    assert "target_word_count" in prompt
    assert "800 ~ 12000" in prompt
    assert "## 前情提要" in prompt
    assert "## 本章劇情發展方向" in prompt
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
    assert "## 上一版規劃（供修正參考）" in prompt
    assert "previous_attempt_ground_truth_events" in prompt
    assert "主角收到密信後準備返城。" in prompt
    assert "- continuity_notes: ['灰鴉的警告尚未處理。']" in prompt
    assert "- recent_entities: ['Kaelen', '灰鴉']" in prompt
    assert "- prior_feedback: []" in prompt
    assert "若上方已提供 previous_attempt_ground_truth_events 或 previous_attempt_narrative_script" in prompt
    assert "優先保留已經合理的事件鏈與章節方向" in prompt
    assert "ground_truth_events 每一條都必須代表本章新增的狀態變化" in prompt
    assert "不得把上一章已完成的交易、發現、對話或衝突" in prompt
    assert "author_goal" in prompt
    assert "must_include_beats" in prompt
    assert "reader_visible_facts" in prompt
    assert "reader_unresolved_questions" in prompt
    assert "private_facts_or_secret_actions" in prompt
    assert "chapter_start_location" in prompt
    assert "chapter_end_location_hint" in prompt
    assert "ending_boundary_rule" in prompt
    assert "forbidden_next_scene_actions" in prompt
    assert "forbidden_reveals" in prompt
    assert "author_safe_continuity_notes" in prompt
    assert "不可原句貼給 author" in prompt
