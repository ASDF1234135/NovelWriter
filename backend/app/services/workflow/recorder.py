from __future__ import annotations

from time import perf_counter
from uuid import uuid4

from app.domain.schema import WorkflowStepLog
from app.services.workflow.context import WorkflowContext


class WorkflowRecorder:
    def __init__(self, context: WorkflowContext) -> None:
        self.context = context
        self.step_index = len(self.context.workflow_repository.list_steps(context.run_id))

    def record(
        self,
        agent_name: str,
        input_payload: dict,
        output_payload: dict,
        masked_payload: dict | None = None,
        token_usage: int = 0,
        latency_ms: int = 0,
        route_decision: str = "",
        status: str = "completed",
    ) -> None:
        self.step_index += 1
        self.context.workflow_repository.append_step(
            WorkflowStepLog(
                step_id=str(uuid4()),
                run_id=self.context.run_id,
                agent_name=agent_name,
                step_index=self.step_index,
                status=status,
                input_payload=input_payload,
                output_payload=output_payload,
                masked_payload=masked_payload or {},
                token_usage=token_usage,
                latency_ms=latency_ms,
                route_decision=route_decision,
            )
        )


def timed() -> float:
    return perf_counter()


def elapsed_ms(start: float) -> int:
    return int((perf_counter() - start) * 1000)
