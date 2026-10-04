"""Unit tests for budget service, stagnation detector, and controller (P3.3 & P3.4)."""

import tempfile
from pathlib import Path

import pytest

from astra_multi.domain.fixtures import sample_state
from astra_multi.domain.models import Issue, IssueSeverity, RunPhase
from astra_multi.orchestration.budget import BudgetExhaustedError, BudgetService
from astra_multi.orchestration.controller import WorkflowController
from astra_multi.orchestration.termination import StagnationDetector
from astra_multi.persistence.sqlite import SQLiteStore


def test_budget_service_atomic_reservation_and_settlement():
    budget = BudgetService(token_limit=1000, cost_limit=1.0, call_limit=5)

    # Make reservation
    op1 = budget.reserve(estimated_tokens=400, estimated_cost=0.4)
    assert budget.total_reserved_tokens == 400
    assert budget.total_reserved_cost == 0.4

    # Settle reservation
    budget.settle(op1, actual_tokens=350, actual_cost=0.35)
    assert budget.total_reserved_tokens == 0
    summary = budget.get_summary()
    assert summary["used_tokens"] == 350
    assert summary["used_cost"] == 0.35
    assert summary["settled_calls"] == 1


def test_budget_service_blocks_when_exceeding_token_limit():
    budget = BudgetService(token_limit=500, cost_limit=1.0)
    budget.reserve(estimated_tokens=400, estimated_cost=0.1)

    with pytest.raises(BudgetExhaustedError, match="Token limit"):
        budget.reserve(estimated_tokens=200, estimated_cost=0.1)


def test_budget_service_blocks_when_exceeding_call_limit():
    budget = BudgetService(call_limit=2)
    op1 = budget.reserve(estimated_tokens=10, estimated_cost=0.01)
    budget.settle(op1, 10, 0.01)

    op2 = budget.reserve(estimated_tokens=10, estimated_cost=0.01)
    budget.settle(op2, 10, 0.01)

    with pytest.raises(BudgetExhaustedError, match="Call limit"):
        budget.reserve(estimated_tokens=10, estimated_cost=0.01)


def test_stagnation_detector_triggers_on_lack_of_progress():
    detector = StagnationDetector(history_window=2)
    state = sample_state()

    # Round 1
    detector.record_round(state, 1)
    assert not detector.is_stagnant()

    # Round 2 with no changes
    detector.record_round(state, 2)
    assert detector.is_stagnant()


def test_workflow_controller_transitions_and_commits():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        with SQLiteStore(db_path) as store:
            state = sample_state()
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="worker-1", ttl=30)

            controller = WorkflowController(store, lease)

            # Transition phase
            updated_state = controller.transition_phase(RunPhase.SNAPSHOT)
            assert updated_state.run.phase == RunPhase.SNAPSHOT
            assert updated_state.run.revision == 2

            # Record issue
            issue = Issue(
                id="ISSUE-TEST-1",
                run_id=state.run.id,
                severity=IssueSeverity.WARNING,
                based_on_revision=0,
                claim="Potential race condition",
                impact="Data corruption under load",
                verification_request="Run concurrency test",
                suggested_resolution="Add mutex lock",
                requirement_ids=["REQ-001"],
            )
            updated_state = controller.record_issue(issue)
            assert len(updated_state.issues) == 1
            assert updated_state.issues[0].id == "ISSUE-TEST-1"
