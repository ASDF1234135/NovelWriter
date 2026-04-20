from app.domain.schema import ExtractedRelation, GraphSnapshot
from app.services.workflow.extraction import _build_extraction_prompt


def test_extraction_prompt_documents_all_edge_types() -> None:
    prompt = _build_extraction_prompt(
        state={
            "story_id": "story_test",
            "chapter_id": 1,
            "active_epoch_id": "epoch_present",
            "pov_character_id": "char_observer",
            "reader_visible_facts": ["城門關閉"],
            "private_facts_or_secret_actions": ["守衛長官暗中監視"],
            "reader_unresolved_questions": ["誰在幕後操盤"],
            "chapter_end_location_hint": "王都西側裂谷",
            "last_known_location": "王都南門",
        },
        graph_snapshot=GraphSnapshot(nodes=[], edges=[]),
        chapter_content="測試章節內容",
        events=[],
    )

    assert "LOCATED_IN" in prompt
    assert "HAS_ITEM" in prompt
    assert "HAS_RELATION" in prompt
    assert "PARTICIPATED_IN" in prompt
    assert "IS_ACTUALLY" in prompt
    assert "HAS_ATTRIBUTE" in prompt
    assert "BELIEVED_AS" in prompt
    assert "KNOWS_ABOUT" in prompt
    assert "BELONGS_TO_EPOCH" in prompt
    assert "HAPPENED_BEFORE" in prompt
    assert "CAUSED" in prompt
    assert "ENFORCED_IN" in prompt
    assert "RESTRICTS" in prompt
    assert "EXEMPT_FROM" in prompt
    assert "RULE" in prompt
    assert "Truth vs publicity" in prompt
    assert "Rhetoric filter" in prompt
    assert "planner_visibility_contract" in prompt
    assert "守衛長官暗中監視" in prompt


def test_believed_as_guideline_forbids_interpersonal_misuse() -> None:
    prompt = _build_extraction_prompt(
        state={
            "story_id": "story_test",
            "chapter_id": 1,
            "active_epoch_id": "epoch_present",
            "pov_character_id": "char_observer",
            "reader_visible_facts": [],
            "private_facts_or_secret_actions": [],
            "reader_unresolved_questions": [],
            "chapter_end_location_hint": "",
            "last_known_location": "",
        },
        graph_snapshot=GraphSnapshot(nodes=[], edges=[]),
        chapter_content="x",
        events=[],
    )
    assert "BELIEVED_AS" in prompt
    assert "do not label trust" in prompt
    assert "HAS_RELATION" in prompt
    assert "IS_ACTUALLY" in prompt


def test_extracted_relation_defaults_to_private() -> None:
    relation = ExtractedRelation(
        relation_type="KNOWS_ABOUT",
    )

    assert relation.is_public is False
