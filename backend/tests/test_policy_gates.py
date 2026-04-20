from app.services.llm import MockLLMClient
from app.services.workflow.policy_gates import run_semantic_gate


class _DummyContext:
    def __init__(self) -> None:
        self.llm_client = MockLLMClient()
        self.output_language = "en"


def test_run_semantic_gate_uses_mock_fallback() -> None:
    gate, llm_result = run_semantic_gate(
        context=_DummyContext(),
        rule_id="rule_demo",
        prompt="demo",
        fallback_decision="warn",
        fallback_confidence=0.5,
    )
    assert llm_result is None
    assert gate.rule_id == "rule_demo"
    assert gate.decision == "warn"
    assert gate.confidence == 0.5
    assert gate.gate_source == "hybrid"

