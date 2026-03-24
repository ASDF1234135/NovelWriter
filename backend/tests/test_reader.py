from app.domain.schema import ReaderOutput, SuggestionType
from app.services.llm import LLMResult
from app.services.workflow.nodes.reader import run_reader
from app.services.workflow.profiles import AgentPromptProfile


class FakeJsonLLMClient:
    def __init__(self, payload: ReaderOutput) -> None:
        self.payload = payload

    def invoke(self, prompt: str) -> LLMResult:
        raise NotImplementedError

    def invoke_text(self, prompt: str, profile: AgentPromptProfile) -> LLMResult:
        raise NotImplementedError

    def invoke_json(self, prompt, response_model, profile):
        return self.payload, LLMResult(content="", token_usage=10, latency_ms=20)


class DummyContext:
    def __init__(self, payload: ReaderOutput) -> None:
        self.llm_client = FakeJsonLLMClient(payload)


def test_reader_approval_uses_score_threshold_not_provider_flag() -> None:
    output = run_reader(
        {
            "target_word_count": 2500,
            "current_draft": "夜色下的草稿，情節完整且可讀。",
        },
        DummyContext(
            ReaderOutput(
                is_approved=False,
                literary_score=76,
                suggestion_type=SuggestionType.MODIFY,
                critique="雖可再潤飾，但整體已達可讀門檻。",
            )
        ),
    )

    assert output["is_approved"] is True
    assert output["literary_score"] == 76
    assert output["suggestion_type"] == SuggestionType.NONE.value


def test_reader_failed_score_keeps_modification_feedback() -> None:
    output = run_reader(
        {
            "target_word_count": 2500,
            "current_draft": "偏短草稿。",
        },
        DummyContext(
            ReaderOutput(
                is_approved=True,
                literary_score=55,
                suggestion_type=SuggestionType.NONE,
                critique="節奏偏平，畫面與情緒層次可再加強。",
            )
        ),
    )

    assert output["is_approved"] is False
    assert output["literary_score"] == 55
    assert output["suggestion_type"] == SuggestionType.MODIFY.value
    assert output["critique"] == "節奏偏平，畫面與情緒層次可再加強。"


def test_reader_short_llm_critique_gets_fallback_hint() -> None:
    output = run_reader(
        {
            "target_word_count": 2500,
            "current_draft": "夜色與陰影交錯的一段文字，用於滿足最低長度。",
        },
        DummyContext(
            ReaderOutput(
                is_approved=True,
                literary_score=40,
                suggestion_type=SuggestionType.NONE,
                critique="差",
            )
        ),
    )

    assert output["is_approved"] is False
    assert "節奏是否拖沓" in output["critique"]
