"""Test suite for Phase 1 [A]: Finalize không được hardcode passed=True."""

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from astra_multi.api.app import create_app
from astra_multi.domain.models import (
    PlanRevision,
    PlanStep,
    RunPhase,
    RunStatus,
)
from astra_multi.exports.finalization import (
    SemanticReviewAssessment,
)
from astra_multi.orchestration.controller import WorkflowController


def _setup_run_with_plan(client: TestClient, app) -> str:
    res = client.post("/api/runs", json={
        "goal": "Test Finalize Semantic Review",
        "requirements": ["REQ 1"],
    })
    run_id = res.json()["run_id"]
    store = app.state.store
    req_id = store.load(run_id).task.requirements[0].id

    lease = store.acquire(run_id, owner="test", ttl=30)
    ctrl = WorkflowController(store, lease, actor="test")
    ctrl.transition_phase(RunPhase.INDEPENDENT_ANALYSIS)
    ctrl.transition_phase(RunPhase.PROPOSE)
    ctrl.transition_phase(RunPhase.REVIEW)
    ctrl.transition_phase(RunPhase.REVISE)

    step = PlanStep(
        id="STEP-1",
        objective="Step 1 objective",
        requirement_ids=[req_id],
        validation="pytest",
        deliverables=["Artifact 1"],
        completion_criteria=["All tests pass"],
    )
    plan = PlanRevision(
        id="PLAN-1",
        run_id=run_id,
        revision=1,
        based_on_revision=0,
        requirements_revision=1,
        snapshot_id=None,
        steps=[step],
    )
    ctrl.commit_plan_revision(plan)
    ctrl.transition_phase(RunPhase.SEMANTIC_REVIEW)
    ctrl.transition_phase(RunPhase.QUALITY_GATE)
    ctrl.transition_phase(RunPhase.EXPORT)
    ctrl.transition_phase(RunPhase.EXPORT, RunStatus.PARTIAL, reason="MVP candidate generated")
    store.release(lease)
    return run_id


def test_finalize_without_semantic_review_returns_partial():
    """(1) finalize khi chưa có semantic review -> PARTIAL."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        art_path = Path(tmpdir) / "artifacts"
        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)
        try:
            with TestClient(app) as client:
                run_id = _setup_run_with_plan(client, app)

                # Attempt finalize WITHOUT semantic review in store
                fin_res = client.post(f"/api/runs/{run_id}/finalize")
                assert fin_res.status_code == 200
                data = fin_res.json()
                assert data["can_finalize"] is False
                assert data["status"] == "PARTIAL"
                assert "Semantic review assessment not provided" in data["reason"]
        finally:
            app.state.store.close()


def test_finalize_with_stale_plan_revision_returns_partial():
    """(2) revision lệch -> PARTIAL."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        art_path = Path(tmpdir) / "artifacts"
        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)
        try:
            with TestClient(app) as client:
                run_id = _setup_run_with_plan(client, app)
                store = app.state.store

                # Save semantic review with stale revision (reviewed revision 0 instead of current 1)
                stale_assessment = SemanticReviewAssessment(
                    passed=True,
                    reviewed_plan_revision=0,
                    feedback="Reviewed old draft",
                    concerns=[],
                )
                store.save_semantic_review(run_id, stale_assessment)

                fin_res = client.post(f"/api/runs/{run_id}/finalize")
                assert fin_res.status_code == 200
                data = fin_res.json()
                assert data["can_finalize"] is False
                assert data["status"] == "PARTIAL"
                assert "stale" in data["reason"].lower()
        finally:
            app.state.store.close()


def test_finalize_with_open_warning_issue_returns_partial():
    """(3) còn issue warning mở -> PARTIAL."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        art_path = Path(tmpdir) / "artifacts"
        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)
        try:
            with TestClient(app) as client:
                run_id = _setup_run_with_plan(client, app)
                store = app.state.store

                # Semantic review was evaluated as passed=False because of an open warning issue
                failed_assessment = SemanticReviewAssessment(
                    passed=False,
                    reviewed_plan_revision=1,
                    feedback="Remaining open warning issue",
                    concerns=["[ISSUE-001] Performance warning under load"],
                )
                store.save_semantic_review(run_id, failed_assessment)

                fin_res = client.post(f"/api/runs/{run_id}/finalize")
                assert fin_res.status_code == 200
                data = fin_res.json()
                assert data["can_finalize"] is False
                assert data["status"] == "PARTIAL"
                assert "Semantic review did not pass" in data["reason"]
        finally:
            app.state.store.close()


def test_finalize_eligible_returns_final():
    """(4) đủ điều kiện -> FINAL."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        art_path = Path(tmpdir) / "artifacts"
        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)
        try:
            with TestClient(app) as client:
                run_id = _setup_run_with_plan(client, app)
                store = app.state.store

                # Save valid semantic review assessment with passed=True and current revision 1
                good_assessment = SemanticReviewAssessment(
                    passed=True,
                    reviewed_plan_revision=1,
                    feedback="All criteria met",
                    concerns=[],
                )
                store.save_semantic_review(run_id, good_assessment)

                fin_res = client.post(f"/api/runs/{run_id}/finalize")
                assert fin_res.status_code == 200
                data = fin_res.json()
                assert data["can_finalize"] is True
                assert data["status"] == "FINAL"
                assert data["blockers"] == []
        finally:
            app.state.store.close()
