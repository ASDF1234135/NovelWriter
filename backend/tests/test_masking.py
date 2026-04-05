from app.services.workflow.masking import (
    build_author_payload,
    build_draft_supervisor_payload,
    build_planner_payload,
    build_plan_supervisor_payload,
)


def test_author_payload_masks_sensitive_state() -> None:
    state = {
        "narrative_script": "安全劇本",
        "chapter_start_location": "舊鐘樓頂層。",
        "author_goal": "讓主角在本章完成一次有效推進。",
        "must_include_beats": ["取得物證", "確認風險升高"],
        "reader_visible_facts": ["物證真實存在"],
        "reader_unresolved_questions": ["幕後黑手是誰"],
        "chapter_end_location_hint": "王都北門外。",
        "ending_state_shift": "主角掌握新證據，但暴露風險提高。",
        "ending_boundary_rule": "本章最遠只能停在王都北門外，不可進入下一個據點。",
        "forbidden_next_scene_actions": ["不可進入北門哨站", "不可直接與接應者會面"],
        "forbidden_reveals": ["不得揭露幕後黑手身份"],
        "tone_direction": "懸疑",
        "target_word_count": 2000,
        "previous_chapter_summary": "上一章主角潛入王都。",
        "current_draft": "第1章\n\n主角在舊鐘樓外停下腳步。",
        "last_known_location": "舊鐘樓。",
        "author_safe_continuity_notes": ["灰鴉的密信尚未解讀。"],
        "recent_entity_names": ["Kaelen", "灰鴉"],
        "draft_feedback": [{"message": "補強轉場"}],
        "reader_feedback": [],
        "ground_truth_events": [{"event_id": "secret", "description": "真相"}],
        "graph_context": "forbidden",
        "plan_feedback": [{"message": "future leak"}],
        "writing_note": ["短句優先", "避免過度抒情"],
    }

    payload = build_author_payload(state)

    dumped = payload.model_dump()
    assert dumped["narrative_script"] == "安全劇本"
    assert dumped["chapter_start_location"] == "舊鐘樓頂層。"
    assert dumped["author_goal"] == "讓主角在本章完成一次有效推進。"
    assert dumped["must_include_beats"] == ["取得物證", "確認風險升高"]
    assert dumped["reader_visible_facts"] == ["物證真實存在"]
    assert dumped["reader_unresolved_questions"] == ["幕後黑手是誰"]
    assert dumped["chapter_end_location_hint"] == "王都北門外。"
    assert dumped["ending_state_shift"] == "主角掌握新證據，但暴露風險提高。"
    assert dumped["ending_boundary_rule"] == "本章最遠只能停在王都北門外，不可進入下一個據點。"
    assert dumped["forbidden_next_scene_actions"] == ["不可進入北門哨站", "不可直接與接應者會面"]
    assert dumped["forbidden_reveals"] == ["不得揭露幕後黑手身份"]
    assert dumped["previous_chapter_summary"] == "上一章主角潛入王都。"
    assert dumped["previous_attempt_draft"] == "第1章\n\n主角在舊鐘樓外停下腳步。"
    assert dumped["last_known_location"] == "舊鐘樓。"
    assert dumped["normalized_length_min"] == 1300
    assert dumped["normalized_length_max"] == 2700
    assert dumped["length_adjustment"] == "NONE"
    assert dumped["author_safe_continuity_notes"] == ["灰鴉的密信尚未解讀。"]
    assert dumped["writing_note"] == ["短句優先", "避免過度抒情"]
    assert "ground_truth_events" not in dumped
    assert "graph_context" not in dumped
    assert "plan_feedback" not in dumped


def test_plan_supervisor_payload_includes_anchor_distance() -> None:
    state = {
        "chapter_id": 1,
        "active_epoch_id": "epoch_present",
        "target_anchor_id": "anchor_06",
        "unachieved_anchors": [
            {
                "anchor_id": "anchor_06",
                "chapter_target": 6,
            }
        ],
        "ground_truth_events": [{"event_id": "e1", "description": "事件", "caused_by_event_id": None}],
        "narrative_script": "主角發現微小異常，為未來危機鋪墊。",
        "chapter_start_location": "王都外環。",
        "chapter_end_location_hint": "王都西門。",
        "ending_boundary_rule": "本章最遠只能停在王都西門。",
        "forbidden_next_scene_actions": ["不可直接進入城外驛站"],
        "must_include_beats": ["發現異常", "前往西門"],
        "previous_chapter_summary": "上一章主角收到密信。",
        "recent_chapter_context": "第1章：主角收到密信，準備離開。",
        "last_known_location": "王都南門。",
        "graph_context": "{}",
        "vector_context": "{}",
        "bible_context": "{}",
    }

    payload = build_plan_supervisor_payload(state)

    assert payload.current_chapter_id == 1
    assert payload.target_anchor_chapter == 6
    assert payload.chapters_until_anchor == 5
    assert payload.partial_convergence_allowed is True
    assert payload.chapter_start_location == "王都外環。"
    assert payload.chapter_end_location_hint == "王都西門。"
    assert payload.ending_boundary_rule == "本章最遠只能停在王都西門。"
    assert payload.forbidden_next_scene_actions == ["不可直接進入城外驛站"]
    assert payload.must_include_beats == ["發現異常", "前往西門"]
    assert payload.previous_chapter_summary == "上一章主角收到密信。"
    assert payload.last_known_location == "王都南門。"


def test_planner_payload_includes_story_premise_volume_and_anchor_context() -> None:
    state = {
        "chapter_id": 1,
        "active_epoch_id": "epoch_present",
        "pov_character_id": "char_public_observer",
        "narrative_directive": "推進劇情",
        "target_anchor_id": "anchor_01",
        "unachieved_anchors": [
            {
                "anchor_id": "anchor_01",
                "title": "主角被迫踏上旅程",
                "description": "主角離開原本安穩場域，正式捲入主線。",
                "chapter_target": 6,
            }
        ],
        "graph_context": "{}",
        "vector_context": "{}",
        "bible_context": "{}",
        "previous_chapter_summary": "上一章主角收到密信。",
        "recent_chapter_context": "第1章：主角收到密信。",
        "last_known_location": "王都南門。",
        "ground_truth_events": [{"event_id": "evt_01", "description": "主角收到密信", "caused_by_event_id": None}],
        "narrative_script": "主角收到密信後準備返城。",
        "continuity_notes": ["灰鴉要求主角回城。"],
        "recent_entity_names": ["Kaelen", "灰鴉"],
        "plan_feedback": [],
        "writing_note": ["短句優先", "避免過度抒情"],
    }

    story = {
        "premise": "一名被流放的年輕騎士回到王都，追查皇室命案背後的真正凶手。",
    }
    volumes = [
        {
            "title": "卷一：命運啟動",
            "summary": "建立世界與主角困境，鋪設核心衝突。",
            "chapter_start": 1,
            "chapter_end": 6,
        }
    ]

    planner_payload = build_planner_payload(
        state,
        story=story,
        volumes=volumes,
    )

    assert planner_payload.story_premise == story["premise"]
    assert planner_payload.current_volume_title == "卷一：命運啟動"
    assert planner_payload.current_volume_summary == "建立世界與主角困境，鋪設核心衝突。"
    assert planner_payload.current_anchor_title == "主角被迫踏上旅程"
    assert planner_payload.current_anchor_description == "主角離開原本安穩場域，正式捲入主線。"
    assert planner_payload.previous_chapter_summary == "上一章主角收到密信。"
    assert planner_payload.last_known_location == "王都南門。"
    assert planner_payload.previous_attempt_ground_truth_events[0].event_id == "evt_01"
    assert planner_payload.previous_attempt_narrative_script == "主角收到密信後準備返城。"
    assert planner_payload.continuity_notes == ["灰鴉要求主角回城。"]
    assert planner_payload.recent_entity_names == ["Kaelen", "灰鴉"]
    assert planner_payload.writing_note == ["短句優先", "避免過度抒情"]


def test_draft_supervisor_payload_includes_normalized_length() -> None:
    state = {
        "chapter_id": 1,
        "active_epoch_id": "epoch_present",
        "target_anchor_id": "anchor_01",
        "unachieved_anchors": [],
        "target_word_count": 10,
        "ground_truth_events": [{"event_id": "e1", "description": "事件", "caused_by_event_id": None}],
        "narrative_script": "劇本",
        "chapter_start_location": "舊鐘樓。",
        "chapter_end_location_hint": "舊鐘樓。",
        "ending_boundary_rule": "本章最遠只能停在舊鐘樓。",
        "forbidden_next_scene_actions": ["不可直接前往地窖"],
        "must_include_beats": ["確認異常"],
        "current_draft": "甲 乙，!?12",
        "previous_chapter_summary": "上一章主角潛入王都。",
        "recent_chapter_context": "第1章：主角潛入王都。",
        "last_known_location": "舊鐘樓。",
        "graph_context": "{}",
        "vector_context": "{}",
        "bible_context": "{}",
    }

    payload = build_draft_supervisor_payload(state)

    assert payload.target_word_count == 10
    assert payload.normalized_current_draft_length == 4
    assert payload.chapter_start_location == "舊鐘樓。"
    assert payload.ending_boundary_rule == "本章最遠只能停在舊鐘樓。"
    assert payload.previous_chapter_summary == "上一章主角潛入王都。"
