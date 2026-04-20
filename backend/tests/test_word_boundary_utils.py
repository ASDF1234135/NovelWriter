from app.services.workflow.utils import (
    latin_word_boundary_search,
    latin_word_boundary_sub,
    looks_like_latin_word,
)


def test_latin_word_boundary_search_does_not_match_substrings() -> None:
    assert looks_like_latin_word("Ash") is True
    assert latin_word_boundary_search("Ash", "clash") is False
    assert latin_word_boundary_search("Ash", "ASH") is True
    assert latin_word_boundary_search("Ash", "Ash.") is True


def test_latin_word_boundary_sub_does_not_redact_inside_other_words() -> None:
    out = latin_word_boundary_sub("key", "[X]", "monkey key keys keyboard")
    # Only whole-word matches should be replaced; \"keyboard\" should remain.
    assert out == "monkey [X] keys keyboard"

