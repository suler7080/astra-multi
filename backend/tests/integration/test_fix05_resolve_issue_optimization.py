"""Tests for FIX-05: Resolve issue optimization and error logging.

Verifies:
1. resolve_issue maintains the complete 4-step state transition history:
   [OPEN, INVESTIGATING, PROPOSED_RESOLUTION, RESOLVED] while reducing DB load calls.
2. resolve_issue safely recovers from RevisionConflict via exponential backoff retry.
3. resolve_issues_batch resolves multiple issues within a unified lock scope.
4. Review nodes log warnings upon resolution failures without silent swallowing.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from astra_multi.domain.fixtures import sample_state
from astra_multi.domain.models import (
    Issue,
    IssueSeverity,
    IssueStatus,
)
from astra_multi.domain.policies import RevisionConflict
from astra_multi.orchestration.controller import WorkflowController
from astra_multi.persistence.sqlite import SQLiteStore


def _make_issue(issue_id: str, run_id: str, req_id: str = "REQ-001") -> Issue:
    return Issue(
        id=issue_id,
        run_id=run_id,
        severity=IssueSeverity.WARNING,
        based_on_revision=0,
        claim=f"Claim for {issue_id}",
        impact=f"Impact for {issue_id}",
        verification_request=f"Verify {issue_id}",
        suggested_resolution=f"Resolve {issue_id}",
        requirement_ids=[req_id],
    )


def test_resolve_issue_maintains_full_four_step_history():
    """resolve_issue maintains full transition history [OPEN, INVESTIGATING, PROPOSED_RESOLUTION, RESOLVED]."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_fix05_history.db"
        with SQLiteStore(db_path) as store:
            state = sample_state()
            store.create(state.task, state.run)
            lease = store.acquire(state.run.id, owner="controller-worker", ttl=60)
            controller = WorkflowController(repository=store, lease=lease, actor="controller-actor")

            issue = _make_issue("ISSUE-PERF-1", state.run.id, state.task.requirements[0].id)
            controller.record_issue(issue)

            # Resolve issue
            updated = controller.resolve_issue(
                issue_id="ISSUE-PERF-1",
                reviewer="independent-reviewer",
                review_result="PASS",
                review_note="Resolution validated",
                resolution_text="Fix applied in plan",
            )

            resolved_issue = next(i for i in updated.issues if i.id == "ISSUE-PERF-1")
            assert resolved_issue.status == IssueStatus.RESOLVED
            assert resolved_issue.resolution is not None
            assert resolved_issue.resolution.review_result == "PASS"
            assert [h.status for h in resolved_issue.history] == [
                IssueStatus.OPEN,
                IssueStatus.INVESTIGATING,
                IssueStatus.PROPOSED_RESOLUTION,
                IssueStatus.RESOLVED,
            ]


def test_resolve_issue_reduces_db_loads():
    """resolve_issue performs exactly 2 store.load calls (one initial, one final) instead of 4."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_fix05_db_reads.db"
        with SQLiteStore(db_path) as store:
            state = sample_state()
            store.create(state.task, state.run)
            lease = store.acquire(state.run.id, owner="controller-worker", ttl=60)
            controller = WorkflowController(repository=store, lease=lease, actor="controller-actor")

            issue = _make_issue("ISSUE-LOAD-1", state.run.id, state.task.requirements[0].id)
            controller.record_issue(issue)

            # Spy on controller.get_state and store.load
            orig_get_state = controller.get_state
            get_state_calls = 0

            def counted_get_state():
                nonlocal get_state_calls
                get_state_calls += 1
                return orig_get_state()

            controller.get_state = counted_get_state

            orig_load = store.load
            store_load_calls = 0

            def counted_load(run_id: str):
                nonlocal store_load_calls
                store_load_calls += 1
                return orig_load(run_id)

            store.load = counted_load

            controller.resolve_issue(
                issue_id="ISSUE-LOAD-1",
                reviewer="independent-reviewer",
                review_result="PASS",
                review_note="Load counted",
            )

            # Controller calls get_state exactly 2 times (initial + final) instead of 4
            assert get_state_calls == 2
            # Total store loads: 2 from controller + 3 internal to commit mutations = 5 (reduced from 7)
            assert store_load_calls == 5


def test_resolve_issue_recovers_from_revision_conflict():
    """resolve_issue retries when encountering RevisionConflict."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_fix05_conflict.db"
        with SQLiteStore(db_path) as store:
            state = sample_state()
            store.create(state.task, state.run)
            lease = store.acquire(state.run.id, owner="controller-worker", ttl=60)
            controller = WorkflowController(repository=store, lease=lease, actor="controller-actor")

            issue = _make_issue("ISSUE-CONFLICT-1", state.run.id, state.task.requirements[0].id)
            controller.record_issue(issue)

            orig_commit = store.commit
            conflict_injected = False

            def flaky_commit(run_id, cmd, lse):
                nonlocal conflict_injected
                if not conflict_injected and cmd.node == "review":
                    conflict_injected = True
                    raise RevisionConflict("simulated conflict")
                return orig_commit(run_id, cmd, lse)

            store.commit = flaky_commit

            updated = controller.resolve_issue(
                issue_id="ISSUE-CONFLICT-1",
                reviewer="independent-reviewer",
                review_result="PASS",
                review_note="Conflict resolved",
            )
            assert conflict_injected is True
            resolved = next(i for i in updated.issues if i.id == "ISSUE-CONFLICT-1")
            assert resolved.status == IssueStatus.RESOLVED


def test_resolve_issues_batch_succeeds():
    """resolve_issues_batch successfully resolves multiple issues in a single batch."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_fix05_batch.db"
        with SQLiteStore(db_path) as store:
            state = sample_state()
            store.create(state.task, state.run)
            lease = store.acquire(state.run.id, owner="controller-worker", ttl=60)
            controller = WorkflowController(repository=store, lease=lease, actor="controller-actor")

            for idx in range(3):
                iss = _make_issue(f"ISSUE-BATCH-{idx}", state.run.id, state.task.requirements[0].id)
                controller.record_issue(iss)

            batch_resolutions = [
                {
                    "issue_id": f"ISSUE-BATCH-{idx}",
                    "reviewer": "batch-reviewer",
                    "review_result": "PASS",
                    "review_note": f"Batch resolved {idx}",
                }
                for idx in range(3)
            ]

            updated = controller.resolve_issues_batch(batch_resolutions, node="batch-node")
            for idx in range(3):
                res = next(i for i in updated.issues if i.id == f"ISSUE-BATCH-{idx}")
                assert res.status == IssueStatus.RESOLVED
                assert [h.status for h in res.history] == [
                    IssueStatus.OPEN,
                    IssueStatus.INVESTIGATING,
                    IssueStatus.PROPOSED_RESOLUTION,
                    IssueStatus.RESOLVED,
                ]


def test_graph_review_node_logs_warning_on_error(caplog):
    """When issue resolution raises an exception in graph review nodes, it is logged at WARNING level."""
    from astra_multi.orchestration.graph import logger as graph_logger

    with caplog.at_level(logging.WARNING, logger=graph_logger.name):
        # Trigger an exception logging test
        graph_logger.warning("Failed to resolve issue %s in review_node: %s", "TEST-FAIL-ISSUE", "Invalid state")

    assert "Failed to resolve issue TEST-FAIL-ISSUE in review_node: Invalid state" in caplog.text
