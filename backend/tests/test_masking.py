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
        "general_world_lore": "短句優先\n避免過度抒情",
        "safe_chapter_rules": "規則：每回合只能行動一次",
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
    assert dumped["general_world_lore"] == "短句優先\n避免過度抒情"
    assert dumped["safe_chapter_rules"] == "規則：每回合只能行動一次"
    assert "ground_truth_events" not in dumped
    assert "graph_context" not in dumped
    assert "plan_feedback" not in dumped


def test_author_payload_redacts_identity_tokens_from_forbidden_reveals() -> None:
    state = {
        "narrative_script": "安全劇本",
        "chapter_start_location": "暗巷",
        "author_goal": "維持懸疑",
        "must_include_beats": [],
        "reader_visible_facts": [],
        "reader_unresolved_questions": [],
        "chapter_end_location_hint": "",
        "ending_state_shift": "",
        "ending_boundary_rule": "",
        "forbidden_next_scene_actions": [],
        "forbidden_reveals": ["不要揭露「夜鴉」的真身分"],
        "tone_direction": "懸疑",
        "target_word_count": 1200,
        "current_draft": "",
        "draft_feedback": [],
        "reader_feedback": [],
        "author_safe_continuity_notes": ["線人其實是夜鴉。"],
        "recent_entity_names": ["夜鴉", "灰鴉"],
        "allowed_identity_reveals_this_chapter": [],
    }
    payload = build_author_payload(state).model_dump()
    assert "夜鴉" not in " ".join(payload["author_safe_continuity_notes"])
    assert "夜鴉" not in payload["recent_entity_names"]
    assert "[REDACTED_IDENTITY]" in " ".join(payload["author_safe_continuity_notes"])


def test_author_payload_does_not_treat_memory_label_as_identity_token() -> None:
    state = {
        "narrative_script": "安全劇本",
        "chapter_start_location": "暗巷",
        "author_goal": "維持懸疑",
        "must_include_beats": [],
        "reader_visible_facts": [],
        "reader_unresolved_questions": [],
        "chapter_end_location_hint": "",
        "ending_state_shift": "",
        "ending_boundary_rule": "",
        "forbidden_next_scene_actions": [],
        "forbidden_reveals": ['Do not reveal true identity marker "Memory 001".'],
        "tone_direction": "懸疑",
        "target_word_count": 1200,
        "current_draft": "",
        "draft_feedback": [],
        "reader_feedback": [],
        "author_safe_continuity_notes": ["Memory 001 is an archive tag, not a person."],
        "recent_entity_names": ["Memory 001", "灰鴉"],
        "allowed_identity_reveals_this_chapter": [],
    }
    payload = build_author_payload(state).model_dump()
    assert "Memory 001" in " ".join(payload["author_safe_continuity_notes"])
    assert "Memory 001" in payload["recent_entity_names"]
    assert "[REDACTED_IDENTITY]" not in " ".join(payload["author_safe_continuity_notes"])


def test_plan_supervisor_payload_includes_dag_candidates() -> None:
    state = {
        "chapter_id": 1,
        "active_epoch_id": "epoch_present",
        "selected_anchor_ids": ["anchor_06"],
        "anchor_nodes": [
            {
                "id": "anchor_06",
                "title": "主角被迫踏上旅程",
                "description": "主角離開原本安穩場域，正式捲入主線。",
                "depends_on": [],
            }
        ],
        "anchor_candidates": ["anchor_06"],
        "resolved_anchors": [],
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
    assert payload.selected_anchor_ids == ["anchor_06"]
    assert payload.ready_anchor_candidates[0]["anchor_id"] == "anchor_06"
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
        "selected_anchor_ids": ["anchor_01"],
        "anchor_nodes": [
            {
                "id": "anchor_01",
                "title": "主角被迫踏上旅程",
                "description": "主角離開原本安穩場域，正式捲入主線。",
                "depends_on": [],
            }
        ],
        "anchor_candidates": ["anchor_01"],
        "resolved_anchors": [],
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
        "general_world_lore": "短句優先\n避免過度抒情",
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
    assert planner_payload.general_world_lore == "短句優先\n避免過度抒情"


def test_draft_supervisor_payload_includes_normalized_length() -> None:
    state = {
        "chapter_id": 1,
        "active_epoch_id": "epoch_present",
        "selected_anchor_ids": ["anchor_01"],
        "anchor_nodes": [],
        "anchor_candidates": [],
        "resolved_anchors": [],
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
        "allowed_identity_reveals_this_chapter": ["灰鴉"],
    }

    payload = build_draft_supervisor_payload(state)

    assert payload.target_word_count == 10
    assert payload.normalized_current_draft_length == 4
    assert payload.chapter_start_location == "舊鐘樓。"
    assert payload.ending_boundary_rule == "本章最遠只能停在舊鐘樓。"
    assert payload.previous_chapter_summary == "上一章主角潛入王都。"
    assert payload.allowed_identity_reveals_this_chapter == ["灰鴉"]


def test_author_payload_includes_temporal_active_character_profiles() -> None:
    state = {
        "chapter_id": 5,
        "narrative_script": "x",
        "tone_direction": "懸疑",
        "target_word_count": 1500,
        "draft_feedback": [],
        "reader_feedback": [],
        "cast_slim_view": [
            {
                "node_id": "char_hero",
                "name": "英雄",
                "personality": "沉穩",
                "speech_style": "短句",
                "fatal_flaw": "固執",
                "habit": "敲桌",
            }
        ],
        "cast_full_view": [
            {
                "node_id": "char_hero",
                "canonical_name": "英雄",
                "role": "protagonist",
                "personality": "沉穩",
                "speech_style": "短句",
                "arc_history": [
                    {
                        "trigger_event_id": "",
                        "trigger_event_summary": "first loss",
                        "chapter_id": 3,
                        "old_personality": "傲慢",
                        "new_personality": "沉穩",
                        "old_speech_style": "鋒利",
                        "new_speech_style": "短句",
                        "source": "PLANNER",
                        "reason": "loss",
                        "updated_at": "2026-04-18T00:00:00+00:00",
                    },
                    {
                        "trigger_event_id": "",
                        "trigger_event_summary": "future",
                        "chapter_id": 8,
                        "old_personality": "沉穩",
                        "new_personality": "冷酷",
                        "old_speech_style": "短句",
                        "new_speech_style": "冷淡",
                        "source": "PLANNER",
                        "reason": "future",
                        "updated_at": "2026-04-18T00:00:00+00:00",
                    },
                ],
            }
        ],
        "recent_entity_names": ["英雄"],
    }
    payload = build_author_payload(state).model_dump()
    profiles = payload["active_character_profiles"]
    assert len(profiles) == 1
    assert profiles[0]["canonical_name"] == "英雄"
    assert "第2章前" in profiles[0]["past_personality_reference"]
    assert "第8章後" not in profiles[0]["past_personality_reference"]


def test_build_author_payload_arc_markers_use_english_when_story_output_language_en() -> None:
    state = {
        "chapter_id": 4,
        "story_output_language": "en",
        "target_word_count": 2000,
        "narrative_script": "",
        "tone_direction": "noir",
        "draft_feedback": [],
        "reader_feedback": [],
        "planned_graph_nodes": [],
        "cast_slim_view": [
            {
                "node_id": "char_hero",
                "name": "Hero",
                "personality": "calm",
                "speech_style": "short",
                "fatal_flaw": "stubborn",
                "habit": "taps",
            }
        ],
        "cast_full_view": [
            {
                "node_id": "char_hero",
                "canonical_name": "Hero",
                "role": "protagonist",
                "personality": "calm",
                "speech_style": "short",
                "arc_history": [
                    {
                        "trigger_event_id": "",
                        "trigger_event_summary": "first loss",
                        "chapter_id": 3,
                        "old_personality": "proud",
                        "new_personality": "calm",
                        "old_speech_style": "sharp",
                        "new_speech_style": "short",
                        "source": "PLANNER",
                        "reason": "loss",
                        "updated_at": "2026-04-18T00:00:00+00:00",
                    },
                ],
            }
        ],
        "recent_entity_names": ["Hero"],
    }
    payload = build_author_payload(state).model_dump()
    ref = payload["active_character_profiles"][0]["past_personality_reference"]
    assert "[Before Ch.2]" in ref
    assert "[After Ch.3]" in ref
