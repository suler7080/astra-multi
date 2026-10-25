"""P6: a semantic-review persistence failure must end the run in a clear state.

``SQLiteStore.save_semantic_review`` propagates write errors (C-3), so the
``semantic_review`` graph node must fail loudly instead of leaving the run
stranded in RUNNING with no trace. This file pins the behavior for both
drivers:

1. Direct ``app.invoke`` (tests / embedded drivers): the node logs the failure
   with full traceback, drives the run to FAILED via the existing terminal
   transition policy (reason carried in ``stop_reason``), and re-raises so the
   driver still sees the original error.
2. ``RunWorker`` (production driver): the same FAILED terminal state is
   reached, exactly one clear terminal transition event is persisted, the
   traceback lands in ``errors/{run_id}.log``, and no lease is left active.

Assertions follow the P6 plan: (a) final run status, (b) error event
type/payload, (c) no dangling lease.
"""

from __future__ import annotations

import asyncio
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from astra_multi.agents.roles import (
    AnalysisOutput,
    DecisionDraft,
    IssueReport,
    IssueResolutionReport,
    ProposalOutput,
    ReviewOutput,
    StepDraft,
    SynthesizerOutput,
)
from astra_multi.api.worker import RunWorker
from astra_multi.context.bundle import ContextBuilder
from astra_multi.domain.fixtures import sample_state
from astra_multi.domain.models import IssueSeverity, RunPhase, RunStatus
from astra_multi.gateway.model_gateway import GatewayConfig, ModelGateway
from astra_multi.orchestration.controller import WorkflowController
from astra_multi.orchestration.graph import (
    WorkflowContext,
    create_workflow_graph,
)
from astra_multi.persistence.sqlite import SQLiteStore
from astra_multi.schemas import ModelResult


def fake_model_adapter(
    provider: str,
    role: str,
    messages: list[dict[str, str]],
    output_schema: Any = None,
    **kwargs: Any,
) -> ModelResult:
    """Deterministic adapter driving the workflow to semantic_review."""
    if output_schema == AnalysisOutput:
        content = AnalysisOutput(
            role="planner" if role == "planner" else "reviewer",
            findings=[f"{role} found service architecture is valid"],
            risks=["Potential lock contention"],
            assumptions=["PostgreSQL database"],
            marker=f"{role}-marker",
        )
    elif output_schema == ProposalOutput:
        content = ProposalOutput(
            approach="Implement robust healthcheck endpoint",
            alternatives=["Ping endpoint"],
            tradeoffs=["Low latency vs full dependency probe"],
            requirement_coverage={"REQ-001": "Direct HTTP handler returns 200"},
            claim_ids=[],
        )
    elif output_schema == ReviewOutput:
        is_semantic = any("SEMANTIC_REVIEW" in m.get("content", "") for m in messages)
        if is_semantic:
            content = ReviewOutput(
                summary="Semantic review: verified timeout addressed",
                reviewed_evidence_ids=[],
                issues=[],
                resolutions=[
                    IssueResolutionReport(
                        issue_id="ISSUE-1",
                        resolution_text="Timeout verified in plan revision",
                        review_result="PASS",
                    )
                ],
            )
        else:
            content = ReviewOutput(
                summary="Review completed with warning",
                reviewed_evidence_ids=[],
                issues=[
                    IssueReport(
                        claim="No timeout specified on health endpoint probe",
                        impact="Possible thread starvation",
                        severity=IssueSeverity.WARNING,
                        verification_request="Verify health endpoint response with network delay simulated",
                        suggested_resolution="Add 2-second timeout",
                        requirement_ids=["REQ-001"],
                    )
                ],
            )
    elif output_schema == SynthesizerOutput:
        content = SynthesizerOutput(
            steps=[
                StepDraft(
                    objective="Implement /health HTTP route",
                    requirement_ids=["REQ-001"],
                    dependencies=[],
                    targets=["app/routes.py"],
                    validation="pytest tests/test_health.py passes",
                    deliverables=["health route implementation"],
                    completion_criteria=["HTTP 200 returned"],
                    evidence_ids=[],
                )
            ],
            decisions=[
                DecisionDraft(
                    question="Which route decorator to use?",
                    chosen="@app.get('/health')",
                    rationale="Standard FastAPI pattern",
                    alternatives=["@app.route"],
                    evidence_ids=[],
                    related_issue_ids=[],
                )
            ],
            risks=["High load on health route"],
            issues_addressed=["ISSUE-1"],
            rationale="FastAPI route provides clean async handling",
        )
    else:
        content = "ok"

    return ModelResult(
        content=content.model_dump(mode="json") if hasattr(content, "model_dump") else content,
        model_id=f"fake-{role}",
        provider="fake",
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        cost_actual_usd=0.001,
    )


def _configure_failure(store: SQLiteStore) -> list[str]:
    """``set_setting`` raises sqlite3.OperationalError exactly for semantic review saves."""
    attempts: list[str] = []
    original = store.settings.set_setting

    def failing_set_setting(key: str, value: str) -> None:
        attempts.append(key)
        if key.startswith("semantic_review:"):
            raise sqlite3.OperationalError("disk I/O error")
        return original(key, value)

    store.settings.set_setting = failing_set_setting  # type: ignore[method-assign]
    return attempts


def _failed_transition_events(store: SQLiteStore, run_id: str) -> list[Any]:
    return [
        ev
        for ev in store.events(run_id)
        if ev.type == "transition_run"
        and (ev.payload or {}).get("result", {}).get("status") == "FAILED"
    ]


def test_direct_graph_invoke_persist_failure_marks_run_failed():
    """Direct invoke: (a) run ends FAILED with a clear stop_reason; (b) one
    clear terminal transition event; original persistence error re-raised."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "p6_direct_invoke.db"
        with SQLiteStore(db_path) as store:
            state = sample_state(repo=False)
            store.create(state.task, state.run, state.snapshot)
            run_id = state.run.id

            attempts = _configure_failure(store)

            lease = store.acquire(run_id, owner="test-direct-driver", ttl=300)
            controller = WorkflowController(store, lease)
            gateway = ModelGateway(
                config=GatewayConfig(enable_output_repair=False),
                provider_adapter=fake_model_adapter,
            )
            wf_ctx = WorkflowContext(
                controller=controller,
                gateway=gateway,
                context_builder=ContextBuilder(store.artifacts),
            )
            app = create_workflow_graph(wf_ctx).compile()

            with pytest.raises(sqlite3.OperationalError):
                app.invoke({"run_id": run_id, "round": 0, "max_rounds": 2, "events": []})

            # The failure path was exercised at the semantic review save itself.
            assert any(key.startswith("semantic_review:") for key in attempts)

            final = store.load(run_id)
            # (a) the run must never remain RUNNING after the save failed
            assert final.run.status == RunStatus.FAILED
            assert final.run.phase == RunPhase.SEMANTIC_REVIEW
            assert final.run.stop_reason is not None
            assert final.run.stop_reason.startswith(
                "Semantic review could not be persisted"
            )
            assert "disk I/O error" in str(final.run.stop_reason)

            # (b) exactly one clear terminal transition event is persisted
            failed_events = _failed_transition_events(store, run_id)
            assert len(failed_events) == 1
            payload = failed_events[0].payload or {}
            assert payload["result"] == {"phase": "SEMANTIC_REVIEW", "status": "FAILED"}

            # The assessment never landed, so downstream readers fail closed.
            assert store.get_semantic_review(run_id) is None


@pytest.mark.asyncio
async def test_worker_run_reaches_failed_releases_lease_and_persists_error():
    """RunWorker driver: (a) run ends FAILED with clear stop_reason; (b) one
    terminal transition event plus the persisted traceback log; (c) no active
    lease remains after the run ends."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "p6_worker_driver.db"
        with SQLiteStore(db_path) as store:
            state = sample_state(repo=False)
            store.create(state.task, state.run, state.snapshot)
            run_id = state.run.id

            _configure_failure(store)
            gateway = ModelGateway(
                config=GatewayConfig(enable_output_repair=False),
                provider_adapter=fake_model_adapter,
            )
            worker = RunWorker(store=store, gateway=gateway)

            worker.start_run(run_id)
            while worker.is_running(run_id):
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.05)

            final = store.load(run_id)
            # (a) final state is a terminal FAILED, not a stuck RUNNING run
            assert final.run.status == RunStatus.FAILED
            assert final.run.phase == RunPhase.SEMANTIC_REVIEW
            assert (final.run.stop_reason or "").startswith(
                "Semantic review could not be persisted"
            )

            # (b) exactly one clear terminal transition event was persisted
            failed_events = _failed_transition_events(store, run_id)
            assert len(failed_events) == 1
            payload = failed_events[0].payload or {}
            assert payload["result"] == {"phase": "SEMANTIC_REVIEW", "status": "FAILED"}

            # The worker still persisted the full traceback for diagnostics.
            err_file = store.artifacts.root / "errors" / f"{run_id}.log"
            assert err_file.exists()
            assert "sqlite3.OperationalError" in err_file.read_text(encoding="utf-8")

            # (c) no dangling lease: every lease row for the run is expired
            rows = store.connection.execute(
                "SELECT COALESCE(expires_at, '') FROM leases WHERE run_id=?",
                (run_id,),
            ).fetchall()
            now = store.clock()
            for (expires_at,) in rows:
                assert expires_at, "lease row must carry an expiry timestamp"
                assert datetime.fromisoformat(expires_at) <= now
