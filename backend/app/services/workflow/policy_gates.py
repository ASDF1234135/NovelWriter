from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.services.llm import LLMResult, MockLLMClient
from app.services.workflow.context import WorkflowContext
from app.services.workflow.output_language import augment_profile_system_prompt
from app.services.workflow.profiles import get_profile


GateSource = Literal["llm", "deterministic", "hybrid"]
GateDecision = Literal["allow", "warn", "block"]


class SemanticGateResult(BaseModel):
    gate_source: GateSource = "llm"
    rule_id: str
    decision: GateDecision = "allow"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_snippet: str = ""
    rationale: str = ""


class HardGateResult(BaseModel):
    gate_source: GateSource = "deterministic"
    rule_id: str
    passed: bool
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence_snippet: str = ""
    rationale: str = ""


class _SemanticGateOutput(BaseModel):
    decision: GateDecision
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_snippet: str = ""
    rationale: str = ""


def run_semantic_gate(
    *,
    context: WorkflowContext,
    rule_id: str,
    prompt: str,
    profile_name: str = "draft_supervisor",
    fallback_decision: GateDecision = "allow",
    fallback_confidence: float = 0.0,
) -> tuple[SemanticGateResult, LLMResult | None]:
    if isinstance(context.llm_client, MockLLMClient):
        return (
            SemanticGateResult(
                gate_source="hybrid",
                rule_id=rule_id,
                decision=fallback_decision,
                confidence=fallback_confidence,
                rationale="Mock client fallback.",
            ),
            None,
        )
    profile = augment_profile_system_prompt(get_profile(profile_name), context.output_language, prompt_kind="audit")
    out, res = context.llm_client.invoke_json(prompt, _SemanticGateOutput, profile)
    return (
        SemanticGateResult(
            gate_source="llm",
            rule_id=rule_id,
            decision=out.decision,
            confidence=out.confidence,
            evidence_snippet=out.evidence_snippet,
            rationale=out.rationale,
        ),
        res,
    )

