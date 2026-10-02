"""Small shared examples for P2/P3 and public repository clients."""

from .models import (
    Issue,
    IssueSeverity,
    PlanRevision,
    PlanStep,
    Requirement,
    Run,
    RunState,
    Snapshot,
    TaskSpec,
)


def sample_state(*, repo: bool = False, run_id: str = "RUN-001") -> RunState:
    task = TaskSpec(
        id="TASK-001",
        goal="Add health endpoint",
        requirements=[
            Requirement(
                id="REQ-001",
                text="Report service health",
                acceptance="GET /health returns 200",
            )
        ],
    )
    snapshot = (
        Snapshot(
            id="SNAP-001",
            source_path="workspace",
            manifest_hash="a" * 64,
            file_hashes={"app.py": "b" * 64},
        )
        if repo
        else None
    )
    run = Run(
        id=run_id,
        task_id=task.id,
        task_revision=1,
        snapshot_id=snapshot.id if snapshot else None,
        mode="repo" if repo else "greenfield",
        config_hash="c" * 64,
    )
    return RunState(run=run, tasks=[task], snapshot=snapshot)


def sample_plan(state: RunState) -> PlanRevision:
    revision = state.plan.revision if state.plan else 0
    return PlanRevision(
        id=f"PLAN-{revision + 1}",
        run_id=state.run.id,
        revision=revision + 1,
        based_on_revision=revision,
        requirements_revision=state.task.revision,
        snapshot_id=state.run.snapshot_id,
        steps=[
            PlanStep(
                id="STEP-001",
                objective="Implement health route",
                requirement_ids=["REQ-001"],
                validation="Run HTTP integration test",
                deliverables=["health route"],
                completion_criteria=["Response status is 200"],
            )
        ],
        issues_addressed=[i.id for i in state.issues],
    )


def sample_issue(state: RunState, issue_id: str = "ISSUE-001") -> Issue:
    return Issue(
        id=issue_id,
        run_id=state.run.id,
        severity=IssueSeverity.BLOCKING,
        based_on_revision=state.plan.revision if state.plan else 0,
        claim="Health failure behavior unspecified",
        impact="Clients may misreport outages",
        verification_request="Verify unhealthy response",
        suggested_resolution="Specify failure response",
        requirement_ids=["REQ-001"],
    )
