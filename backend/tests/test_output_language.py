from app.services.workflow.output_language import (
    augment_profile_system_prompt,
    chapter_context_line,
    chapter_heading_line,
    default_chapter_target_words,
    heading_first_line_matches_chapter,
    normalize_output_language,
    output_language_audit_contract_block,
    output_language_contract_block,
    strip_leading_chapter_heading_line,
)
from app.services.workflow.profiles import AgentPromptProfile


def test_output_language_contract_block_lists_language_and_rules() -> None:
    block = output_language_contract_block("zh-Hant")
    assert "Traditional Chinese" in block
    assert "CRITICAL LANGUAGE REQUIREMENT" in block
    assert "ENUM" in block
    assert "Do NOT translate or transliterate" in block


def test_augment_profile_appends_contract_once() -> None:
    base = AgentPromptProfile(
        agent_name="x",
        system_prompt="You are a test agent.",
        model="m",
        temperature=0.0,
    )
    a1 = augment_profile_system_prompt(base, "en")
    assert "CRITICAL LANGUAGE REQUIREMENT" in a1.system_prompt
    assert a1.system_prompt.startswith("You are a test agent.")
    a2 = augment_profile_system_prompt(a1, "en")
    assert a2.system_prompt.count("CRITICAL LANGUAGE REQUIREMENT") == 1


def test_output_language_audit_contract_block_no_critical_opener() -> None:
    block = output_language_audit_contract_block("zh-Hant")
    assert "OUTPUT_LANGUAGE_AUDIT:" in block
    assert "Traditional Chinese" in block
    assert "CRITICAL LANGUAGE REQUIREMENT" not in block
    assert "pre-written" in block


def test_default_chapter_target_words_en_vs_cjk() -> None:
    assert default_chapter_target_words("en") == 360
    assert default_chapter_target_words("zh-Hant") == 2500
    assert default_chapter_target_words("zh-Hans") == 2500


def test_chapter_heading_line_respects_language() -> None:
    assert chapter_heading_line(12, "en") == "Chapter 12"
    assert chapter_heading_line(12, "zh-Hant") == "第12章"


def test_chapter_context_line_respects_language() -> None:
    assert chapter_context_line(2, "summary", "en").startswith("Chapter 2:")
    assert "第2章：" in chapter_context_line(2, "summary", "zh-Hans")


def test_strip_leading_chapter_heading_line_zh_and_en() -> None:
    assert strip_leading_chapter_heading_line("第 3 章\n\nBody") == "Body"
    assert strip_leading_chapter_heading_line("Chapter 3\n\nBody") == "Body"


def test_heading_first_line_matches_chapter_accepts_both_scripts() -> None:
    assert heading_first_line_matches_chapter("Chapter 5", 5) is True
    assert heading_first_line_matches_chapter("第5章", 5) is True
    assert heading_first_line_matches_chapter("Chapter 5", 4) is False


def test_augment_profile_audit_kind_skips_generative_block() -> None:
    base = AgentPromptProfile(
        agent_name="draft_supervisor",
        system_prompt="You audit drafts.",
        model="m",
        temperature=0.0,
    )
    aud = augment_profile_system_prompt(base, "en", prompt_kind="audit")
    assert "OUTPUT_LANGUAGE_AUDIT:" in aud.system_prompt
    assert "CRITICAL LANGUAGE REQUIREMENT" not in aud.system_prompt


def test_normalize_output_language_supports_common_zh_aliases() -> None:
    assert normalize_output_language("zh-CN") == "zh-Hans"
    assert normalize_output_language("zh-TW") == "zh-Hant"
    assert normalize_output_language(" zh-sg ") == "zh-Hans"
    assert normalize_output_language("unknown-lang") == "zh-Hant"
