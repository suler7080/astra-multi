"""Export JSON Schema and valid/invalid public fixtures."""

import argparse
import json
from pathlib import Path

from pydantic import JsonValue

from .fixtures import sample_issue, sample_plan, sample_state
from .models import (
    ArtifactRef,
    BudgetReservation,
    CheckpointRef,
    Claim,
    Contract,
    Decision,
    Event,
    Evidence,
    Issue,
    IssueResolution,
    Lease,
    ModelCall,
    OperationRecord,
    PlanRevision,
    PlanStep,
    Proposal,
    Question,
    Run,
    RunState,
    Snapshot,
    TaskSpec,
    ToolCall,
    ValidationResult,
    utc_now,
)

CONTRACTS: tuple[type[Contract], ...] = (
    TaskSpec,
    Run,
    Snapshot,
    Claim,
    Evidence,
    Proposal,
    Issue,
    Decision,
    PlanRevision,
    PlanStep,
    ToolCall,
    ModelCall,
    Event,
    Question,
    ValidationResult,
    BudgetReservation,
    OperationRecord,
    ArtifactRef,
    CheckpointRef,
    Lease,
    RunState,
)


def samples() -> dict[str, Contract]:
    state = sample_state(repo=True)
    now = utc_now()
    plan = sample_plan(state)
    snapshot = state.snapshot
    assert snapshot is not None
    return {
        "TaskSpec": state.task,
        "Run": state.run,
        "GreenfieldRun": sample_state().run,
        "Snapshot": snapshot,
        "Claim": Claim(
            id="CLAIM",
            run_id=state.run.id,
            text="Health response unverified",
            kind="unknown",
            snapshot_id=state.run.snapshot_id,
        ),
        "Evidence": Evidence(
            id="EVID",
            run_id=state.run.id,
            source_type="document",
            locator="requirement",
            content_hash="d" * 64,
            captured_at=now,
            snapshot_id=None,
        ),
        "Proposal": Proposal(
            id="PROP",
            run_id=state.run.id,
            author_role="planner",
            base_revision=0,
            approach="Add HTTP health route",
        ),
        "Issue": sample_issue(state),
        "Decision": Decision(
            id="DEC",
            run_id=state.run.id,
            question="Transport",
            chosen="HTTP",
            rationale="Matches client",
        ),
        "PlanRevision": plan,
        "PlanStep": plan.steps[0],
        "ToolCall": ToolCall(
            id="TOOL",
            run_id=state.run.id,
            request_hash="e" * 64,
            arguments_redacted={"command": "pytest"},
            environment="sandbox",
            snapshot_id=state.run.snapshot_id,
            exit_code=None,
            output_artifact=None,
            started_at=now,
            finished_at=None,
        ),
        "ModelCall": ModelCall(
            id="MODEL",
            run_id=state.run.id,
            role="planner",
            provider="fake",
            model_id="fixture",
            prompt_version="1",
            input_hash="f" * 64,
        ),
        "Event": Event(
            id="EVENT",
            run_id=state.run.id,
            sequence=1,
            type="run_created",
            actor="controller",
            revision=1,
            payload={"task_id": state.task.id},
            timestamp=now,
        ),
        "Question": Question(
            id="QUESTION", run_id=state.run.id, text="Is authentication required?"
        ),
        "ValidationResult": ValidationResult(
            id="VALIDATION", run_id=state.run.id, expected="GET /health returns 200"
        ),
        "BudgetReservation": BudgetReservation(
            id="RESERVATION",
            run_id=state.run.id,
            operation_id="model-1",
            tokens=100,
            cost=0.01,
        ),
        "OperationRecord": OperationRecord(
            id="OPERATION",
            run_id=state.run.id,
            node="revise",
            logical_operation_id="plan-1",
            request_hash="a" * 64,
            revision=2,
            event_sequence=2,
            result={"plan_id": plan.id, "plan_revision": 1},
        ),
        "ArtifactRef": ArtifactRef(content_hash="a" * 64, size=12),
        "CheckpointRef": CheckpointRef(
            run_id=state.run.id,
            revision=1,
            task_id=state.task.id,
            task_revision=1,
            plan_id=None,
        ),
        "Lease": Lease(
            run_id=state.run.id,
            owner="worker",
            token="sample-token",
            epoch=1,
            expires_at=now,
        ),
        "RunState": state,
        "IssueResolution": IssueResolution(
            text="Candidate addresses health failure",
            reviewer="reviewer",
            reviewed_revision=1,
            review_result="PASS",
            review_note="Reviewed candidate",
        ),
    }


def invalid_samples() -> dict[str, dict[str, JsonValue]]:
    run = sample_state().run.model_dump(mode="json")
    return {
        "missing_snapshot_reference": {
            key: value for key, value in run.items() if key != "snapshot_id"
        },
        "invalid_phase": {**run, "phase": "FINAL"},
        "greenfield_with_snapshot": {**run, "snapshot_id": "SNAP-001"},
        "naive_timestamp": {**run, "created_at": "2026-10-02T00:00:00"},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    output = parser.parse_args().output
    output.mkdir(parents=True, exist_ok=True)
    schemas = {
        contract.__name__: contract.model_json_schema() for contract in CONTRACTS
    }
    fixtures = {
        name: sample.model_dump(mode="json") for name, sample in samples().items()
    }
    (output / "schemas.json").write_text(
        json.dumps(schemas, indent=2) + "\n", encoding="utf-8"
    )
    (output / "samples.json").write_text(
        json.dumps({"valid": fixtures, "invalid_runs": invalid_samples()}, indent=2)
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
