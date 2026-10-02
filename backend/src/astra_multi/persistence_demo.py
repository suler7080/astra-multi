"""Public repository example: python -m astra_multi.persistence_demo WORKSPACE."""

import argparse
from pathlib import Path

from astra_multi.domain.commands import AddRecord, ChangeIssue, CommitPlan, Mutation
from astra_multi.domain.fixtures import sample_issue, sample_plan, sample_state
from astra_multi.domain.models import IssueResolution, IssueStatus
from astra_multi.domain.repositories import RunRepository
from astra_multi.persistence import CheckpointBridge, SQLiteStore


def write_example(repository: RunRepository, lease_owner: SQLiteStore) -> str:
    state = sample_state()
    repository.create(state.task, state.run)
    lease = lease_owner.acquire(state.run.id, "demo")
    bridge = CheckpointBridge(repository)
    checkpoint = bridge.reference(state.run.id)
    issue = sample_issue(state)
    commands: list[Mutation] = [
        AddRecord(
            expected_revision=1,
            node="review",
            logical_operation_id="issue",
            actor="reviewer",
            record=issue,
        ),
        ChangeIssue(
            expected_revision=2,
            node="review",
            logical_operation_id="investigate",
            actor="controller",
            issue_id=issue.id,
            status=IssueStatus.INVESTIGATING,
            reason="Investigate failure behavior",
        ),
        CommitPlan(
            expected_revision=3,
            node="revise",
            logical_operation_id="candidate",
            actor="planner",
            plan=sample_plan(state.model_copy(update={"issues": [issue]})),
        ),
        ChangeIssue(
            expected_revision=4,
            node="review",
            logical_operation_id="propose_resolution",
            actor="planner",
            issue_id=issue.id,
            status=IssueStatus.PROPOSED_RESOLUTION,
            reason="Specify HTTP failure contract",
            resolution=IssueResolution(
                text="Health route and failure validation specified"
            ),
        ),
        ChangeIssue(
            expected_revision=5,
            node="review",
            logical_operation_id="resolve",
            actor="controller",
            issue_id=issue.id,
            status=IssueStatus.RESOLVED,
            reason="Reviewer accepted candidate",
            resolution=IssueResolution(
                text="Health route and failure validation specified",
                reviewed_revision=1,
                reviewer="reviewer",
                review_result="PASS",
                review_note="Candidate covers HTTP contract",
            ),
        ),
    ]
    for command in commands:
        _, checkpoint = bridge.commit(checkpoint, command, lease)
    lease_owner.release(lease)
    return state.run.id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    args = parser.parse_args()
    database = args.workspace / "domain.sqlite"
    with SQLiteStore(database) as store:
        run_id = write_example(store, store)
    with SQLiteStore(database) as reopened:
        state = reopened.load(run_id)
        print(state.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
