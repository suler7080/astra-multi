"""Regression tests for ContextOverflow fix (greenfield + large plan/issues)."""

from astra_multi.context.bundle import (
    ContextBuilder,
    ContextLimits,
    ContextOverflow,
    orchestration_limits,
)
from astra_multi.domain.fixtures import sample_issue, sample_state
from astra_multi.domain.models import PlanRevision, PlanStep, RunPhase
from astra_multi.persistence.sqlite import SQLiteStore


def _large_state():
    state = sample_state()
    steps = [
        PlanStep(
            id=f"STEP-{i + 1:03d}",
            objective="X" * 800,
            requirement_ids=["REQ-001"],
            validation="Y" * 500,
            deliverables=["d" * 300],
            completion_criteria=["c" * 300],
        )
        for i in range(10)
    ]
    plan = PlanRevision(
        id="PLAN-1",
        run_id=state.run.id,
        revision=1,
        based_on_revision=0,
        requirements_revision=1,
        snapshot_id=None,
        steps=steps,
        issues_addressed=[],
    )
    state = state.model_copy(update={"plan": plan})
    issues = [
        sample_issue(state, f"ISSUE-{i + 1:03d}").model_copy(
            update={
                "claim": "C" * 600,
                "impact": "I" * 600,
                "suggested_resolution": "R" * 600,
                "verification_request": "V" * 400,
            }
        )
        for i in range(10)
    ]
    return state.model_copy(update={"issues": issues})


def test_large_plan_issues_truncate_instead_of_raise(tmp_path):
    store = SQLiteStore(tmp_path / "s.sqlite")
    try:
        state = _large_state()
        builder = ContextBuilder(store.artifacts)
        bundle = builder.build_context(
            state, "planner", RunPhase.REVIEW, [], ContextLimits(max_tokens=4000)
        )
        assert bundle.token_count <= 4000
        assert "baseline_notes" in bundle.content
    finally:
        store.close()


def test_task_alone_huge_still_raises_with_details(tmp_path):
    store = SQLiteStore(tmp_path / "s2.sqlite")
    try:
        state = sample_state()
        big_task = state.task.model_copy(update={"goal": "G" * 10000})
        state = state.model_copy(update={"task": big_task, "tasks": [big_task]})
        builder = ContextBuilder(store.artifacts)
        try:
            builder.build_context(
                state,
                "planner",
                RunPhase.INDEPENDENT_ANALYSIS,
                [],
                ContextLimits(max_tokens=4000),
            )
        except ContextOverflow as exc:
            msg = str(exc)
            assert "total=" in msg
            assert "ASTRA_MULTI_MAX_CONTEXT_BYTES" in msg
        else:
            raise AssertionError("expected ContextOverflow")
    finally:
        store.close()


def test_orchestration_limits_default_and_env(monkeypatch):
    monkeypatch.delenv("ASTRA_MULTI_MAX_CONTEXT_BYTES", raising=False)
    assert orchestration_limits().max_tokens == 12000
    monkeypatch.setenv("ASTRA_MULTI_MAX_CONTEXT_BYTES", "4000")
    assert orchestration_limits().max_tokens == 4000
