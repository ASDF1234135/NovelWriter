from app.domain.schema import HitlAnchorResolutionRequest, HitlReason, StoryInput, WorkflowStatus
from tests.test_workflow_service import build_initial_state, build_service


def test_hitl_anchor_continue_unresolved_resumes_profile_expander(tmp_path) -> None:
    service = build_service(str(tmp_path / "workflow_hitl_anchor_continue.sqlite3"))
    story = service.create_story(StoryInput(title="T", premise="p", bible={}, target_total_words=12000))
    base = build_initial_state(story["story_id"], 1, [], "trace-anchor-continue")
    base["requires_hitl"] = True
    base["workflow_status"] = WorkflowStatus.WAITING_HITL.value
    base["hitl_reason"] = HitlReason.ANCHOR_RESOLUTION_FAILED
    base["resume_from"] = "anchor_resolve"
    base["resolved_anchors"] = []
    run = service.workflow_repository.create_run(story["story_id"], 1, base)
    service.apply_hitl_anchor_resolution(
        run.run_id,
        HitlAnchorResolutionRequest(action="continue_unresolved", reason="human: not achieved, continue"),
    )
    st = service.workflow_repository.get_run_state(run.run_id)
    assert st["requires_hitl"] is False
    assert st["resume_from"] == "profile_expander"
    assert st["resolved_anchors"] == []
