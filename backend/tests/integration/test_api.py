"""Integration tests for FastAPI endpoints (P5.1, P5.2)."""

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from astra_multi.api.app import create_app
from astra_multi.domain.commands import CommitPlan
from astra_multi.domain.models import PlanRevision, PlanStep


def test_api_create_run_and_idempotency():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "api.db"
        art_path = Path(tmpdir) / "artifacts"
        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)
        try:
            with TestClient(app) as client:
                payload = {
                    "goal": "Build Order Service",
                    "requirements": ["Process orders", "Integrate warehouse"],
                    "idempotency_key": "IDEM-TEST-1",
                }

                # First request
                res1 = client.post("/api/runs", json=payload)
                assert res1.status_code == 202
                data1 = res1.json()
                assert "run_id" in data1
                assert data1["status"] == "RUNNING"
                run_id = data1["run_id"]

                # Re-send same idempotency key and same payload -> returns same run_id
                res2 = client.post("/api/runs", json=payload)
                assert res2.status_code == 202
                data2 = res2.json()
                assert data2["run_id"] == run_id

                # Re-send same idempotency key with different payload -> 409 Conflict
                diff_payload = {
                    "goal": "Different goal",
                    "requirements": ["Other req"],
                    "idempotency_key": "IDEM-TEST-1",
                }
                res3 = client.post("/api/runs", json=diff_payload)
                assert res3.status_code == 409
        finally:
            app.state.store.close()


def test_api_list_and_get_run_detail():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "api.db"
        art_path = Path(tmpdir) / "artifacts"
        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)
        try:
            with TestClient(app) as client:
                # Create
                res = client.post("/api/runs", json={
                    "goal": "Build Inventory Service",
                    "requirements": ["Track stock"],
                })
                run_id = res.json()["run_id"]

                # List
                list_res = client.get("/api/runs")
                assert list_res.status_code == 200
                runs = list_res.json()
                assert len(runs) >= 1
                assert any(r["run_id"] == run_id for r in runs)

                # Detail
                detail_res = client.get(f"/api/runs/{run_id}")
                assert detail_res.status_code == 200
                detail = detail_res.json()
                assert detail["run_id"] == run_id
                assert detail["goal"] == "Build Inventory Service"

                # Not found
                res_404 = client.get("/api/runs/NONEXISTENT")
                assert res_404.status_code == 404
        finally:
            app.state.store.close()


def test_api_cancel_and_resume():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "api.db"
        art_path = Path(tmpdir) / "artifacts"
        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)
        try:
            with TestClient(app) as client:
                res = client.post("/api/runs", json={
                    "goal": "Test Cancellation",
                    "requirements": ["Req 1"],
                })
                run_id = res.json()["run_id"]

                # Cancel
                cancel_res = client.post(f"/api/runs/{run_id}/cancel", json={"reason": "User stop"})
                assert cancel_res.status_code == 200
                assert cancel_res.json()["status"] == "CANCELLED"

                # Verify detail status
                detail_res = client.get(f"/api/runs/{run_id}")
                assert detail_res.json()["status"] == "CANCELLED"
        finally:
            app.state.store.close()


def test_api_export_and_validate():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "api.db"
        art_path = Path(tmpdir) / "artifacts"
        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)
        try:
            with TestClient(app) as client:
                res = client.post("/api/runs", json={
                    "goal": "Test Export",
                    "requirements": ["Req A"],
                })
                run_id = res.json()["run_id"]

                # Commit a plan directly via store
                store = app.state.store
                plan = PlanRevision(
                    id="PLAN-EXP",
                    run_id=run_id,
                    revision=1,
                    based_on_revision=0,
                    requirements_revision=1,
                    snapshot_id=None,
                    steps=[
                        PlanStep(
                            id="STEP-1",
                            objective="Implement feature",
                            requirement_ids=["REQ-001"],
                            validation="pytest",
                            deliverables=["feature.py"],
                            completion_criteria=["tests pass"],
                        )
                    ],
                )
                lease = store.acquire(run_id, owner="test", ttl=30)
                store.commit(run_id, CommitPlan(expected_revision=1, node="test", logical_operation_id="op-exp", actor="test", plan=plan), lease)
                store.release(lease)

                # Validate
                val_res = client.post(f"/api/runs/{run_id}/validate")
                assert val_res.status_code == 200
                assert val_res.json()["passed"] is True

                # Finalize
                fin_res = client.post(f"/api/runs/{run_id}/finalize")
                assert fin_res.status_code == 200
                assert fin_res.json()["status"] == "FINAL"

                # Export JSON
                exp_json = client.get(f"/api/runs/{run_id}/export?format=json")
                assert exp_json.status_code == 200
                assert exp_json.json()["schema_version"] == 1
                assert exp_json.json()["metadata"]["status"] == "FINAL"

                # Export Markdown
                exp_md = client.get(f"/api/runs/{run_id}/export?format=markdown")
                assert exp_md.status_code == 200
                assert "Test Export" in exp_md.text
                assert "FINAL" in exp_md.text
        finally:
            app.state.store.close()


def test_api_questions_and_resume():
    from astra_multi.domain.models import Question, RunStatus
    from astra_multi.orchestration.controller import WorkflowController

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "api.db"
        art_path = Path(tmpdir) / "artifacts"
        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)
        try:
            with TestClient(app) as client:
                res = client.post("/api/runs", json={
                    "goal": "Test Questions and Resume",
                    "requirements": ["Req Q1"],
                })
                run_id = res.json()["run_id"]

                # Ask a question FIRST, then transition to WAITING_FOR_INPUT
                store = app.state.store
                lease = store.acquire(run_id, owner="test", ttl=30)
                ctrl = WorkflowController(store, lease, actor="test")
                q = Question(
                    id="Q-001",
                    run_id=run_id,
                    text="Which database should we use?",
                    blocking=True,
                    requirement_ids=["REQ-001"],
                )
                ctrl.ask_question(q)
                current_phase = ctrl.get_state().run.phase
                ctrl.transition_phase(current_phase, RunStatus.WAITING_FOR_INPUT, reason="Waiting for clarification")
                store.release(lease)

                # Verify pending question in detail
                detail = client.get(f"/api/runs/{run_id}").json()
                assert detail["status"] == "WAITING_FOR_INPUT"
                assert len(detail["pending_questions"]) == 1
                assert detail["pending_questions"][0]["id"] == "Q-001"

                # Test answer with invalid expected_revision -> 409 Conflict
                conflict_res = client.post(f"/api/runs/{run_id}/answers", json={
                    "question_id": "Q-001",
                    "answer": "Use PostgreSQL 16",
                    "expected_revision": 999,
                })
                assert conflict_res.status_code == 409

                # Answer the question with valid expected_revision
                ans_res = client.post(f"/api/runs/{run_id}/answers", json={
                    "question_id": "Q-001",
                    "answer": "Use PostgreSQL 16",
                    "expected_revision": detail["revision"],
                })
                assert ans_res.status_code == 200
                assert ans_res.json()["question_id"] == "Q-001"

                # Resume run
                res_resume = client.post(f"/api/runs/{run_id}/resume")
                assert res_resume.status_code == 200
                assert res_resume.json()["status"] == "RUNNING"
        finally:
            app.state.store.close()


def test_api_entity_queries_and_sse():
    from astra_multi.domain.models import Decision, Issue, IssueSeverity, RunStatus
    from astra_multi.orchestration.controller import WorkflowController

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "api.db"
        art_path = Path(tmpdir) / "artifacts"
        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)
        try:
            with TestClient(app) as client:
                res = client.post("/api/runs", json={
                    "goal": "Test Entities & SSE",
                    "requirements": ["Req SSE"],
                })
                run_id = res.json()["run_id"]

                # Add issue and decision
                store = app.state.store
                lease = store.acquire(run_id, owner="test", ttl=30)
                ctrl = WorkflowController(store, lease, actor="test")
                issue = Issue(
                    id="ISS-001",
                    run_id=run_id,
                    severity=IssueSeverity.WARNING,
                    based_on_revision=0,
                    claim="Memory footprint might be high",
                    impact="Potential OOM in constrained environments",
                    suggested_resolution="Tune memory limits or use Redis",
                    verification_request="Run load test",
                    requirement_ids=["REQ-001"],
                )
                ctrl.record_issue(issue)
                decision = Decision(
                    id="DEC-001",
                    run_id=run_id,
                    question="Which caching strategy to employ?",
                    chosen="Redis cluster",
                    rationale="Mitigates database latency",
                    alternatives=["Memcached", "In-memory LRU"],
                )
                ctrl.record_decision(decision)

                # Cancel run to make it terminal for SSE stream end
                ctrl.transition_phase(ctrl.get_state().run.phase, RunStatus.CANCELLED, reason="Done test")
                store.release(lease)

                # Test queries
                issues_res = client.get(f"/api/runs/{run_id}/issues")
                assert issues_res.status_code == 200
                assert len(issues_res.json()) == 1
                assert issues_res.json()[0]["id"] == "ISS-001"

                dec_res = client.get(f"/api/runs/{run_id}/decisions")
                assert dec_res.status_code == 200
                assert len(dec_res.json()) == 1
                assert dec_res.json()[0]["id"] == "DEC-001"

                ev_res = client.get(f"/api/runs/{run_id}/evidence")
                assert ev_res.status_code == 200
                assert isinstance(ev_res.json(), list)

                # Test SSE endpoint
                sse_res = client.get(f"/api/runs/{run_id}/events")
                assert sse_res.status_code == 200
                assert "text/event-stream" in sse_res.headers["content-type"]
                body_text = sse_res.text
                assert "event: " in body_text
                assert "run_completed" in body_text

                # Test SSE with Last-Event-ID header replay
                sse_replay_res = client.get(f"/api/runs/{run_id}/events", headers={"Last-Event-ID": "2"})
                assert sse_replay_res.status_code == 200
                assert "id: 1\n" not in sse_replay_res.text
        finally:
            app.state.store.close()


def test_api_serves_frontend():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "api.db"
        art_path = Path(tmpdir) / "artifacts"
        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)
        try:
            with TestClient(app) as client:
                res = client.get("/")
                assert res.status_code == 200
                assert "text/html" in res.headers["content-type"]
                assert "Astra Multi" in res.text
        finally:
            app.state.store.close()
