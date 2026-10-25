"""Integration tests for FastAPI endpoints (P5.1, P5.2)."""

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from astra_multi.api.app import create_app
from astra_multi.domain.commands import CommitPlan, TransitionRun
from astra_multi.domain.models import PlanRevision, PlanStep, RunPhase, RunStatus


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
                req_id = store.load(run_id).task.requirements[0].id
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
                            requirement_ids=[req_id],
                            validation="pytest",
                            deliverables=["feature.py"],
                            completion_criteria=["tests pass"],
                        )
                    ],
                )
                lease = store.acquire(run_id, owner="test", ttl=30)
                store.commit(run_id, CommitPlan(expected_revision=1, node="test", logical_operation_id="op-exp", actor="test", plan=plan), lease)
                current_phase = store.load(run_id).run.phase
                store.commit(
                    run_id,
                    TransitionRun(
                        expected_revision=2,
                        node="export",
                        logical_operation_id="export-partial",
                        actor="worker",
                        phase=current_phase,
                        status=RunStatus.PARTIAL,
                        reason="MVP candidate generated (awaiting P4 quality certification)",
                    ),
                    lease,
                )
                store.release(lease)

                # Validate
                val_res = client.post(f"/api/runs/{run_id}/validate")
                assert val_res.status_code == 200
                assert val_res.json()["passed"] is True

                # Finalize
                from astra_multi.exports.finalization import SemanticReviewAssessment
                store.save_semantic_review(
                    run_id,
                    SemanticReviewAssessment(
                        passed=True,
                        reviewed_plan_revision=1,
                        feedback="Requirements met",
                        concerns=[],
                    ),
                )
                fin_res = client.post(f"/api/runs/{run_id}/finalize")
                assert fin_res.status_code == 200
                assert fin_res.json()["status"] == "FINAL"
                assert fin_res.json()["can_finalize"] is True
                assert fin_res.json()["blockers"] == []

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
                req_id = store.load(run_id).task.requirements[0].id
                lease = store.acquire(run_id, owner="test", ttl=30)
                ctrl = WorkflowController(store, lease, actor="test")
                q = Question(
                    id="Q-001",
                    run_id=run_id,
                    text="Which database should we use?",
                    blocking=True,
                    requirement_ids=[req_id],
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
                req_id = store.load(run_id).task.requirements[0].id
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
                    requirement_ids=[req_id],
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
                assert "event: transition_run" in body_text
                assert "event: transition_phase" in body_text
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


def test_api_get_run_logs():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "api.db"
        art_path = Path(tmpdir) / "artifacts"
        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)
        try:
            with TestClient(app) as client:
                # 404 on non-existent run
                res_404 = client.get("/api/runs/RUN-NONEXISTENT/logs")
                assert res_404.status_code == 404

                # Create run
                create_res = client.post(
                    "/api/runs",
                    json={"goal": "Logging Test Run", "requirements": ["Log Requirement"]},
                )
                run_id = create_res.json()["run_id"]

                # Get logs
                logs_res = client.get(f"/api/runs/{run_id}/logs")
                assert logs_res.status_code == 200
                logs = logs_res.json()
                assert len(logs) >= 1
                assert logs[0]["level"] == "INFO"
                assert logs[0]["node"] == "intake"
                assert "Initialized run" in logs[0]["message"]

                # Cancel run to produce terminal state with reason
                client.post(f"/api/runs/{run_id}/cancel", json={"reason": "Test cancel reason"})
                logs_res_after = client.get(f"/api/runs/{run_id}/logs")
                assert logs_res_after.status_code == 200
                logs_after = logs_res_after.json()
                assert any("Test cancel reason" in l["message"] for l in logs_after)
        finally:
            app.state.store.close()


def test_api_clone_run_lineage_and_immutability():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "api.db"
        art_path = Path(tmpdir) / "artifacts"
        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)
        try:
            with TestClient(app) as client:
                # 1. Create parent run
                parent_payload = {
                    "goal": "Build Distributed Cache",
                    "requirements": ["In-memory LRU eviction", "Replication over TCP"],
                    "mode": "greenfield",
                    "max_rounds": 4,
                    "token_limit": 150000,
                    "cost_limit": 3.5,
                }
                res_parent = client.post("/api/runs", json=parent_payload)
                assert res_parent.status_code == 202
                parent_id = res_parent.json()["run_id"]

                # Verify get_run returns detailed parameters
                detail_parent = client.get(f"/api/runs/{parent_id}").json()
                assert detail_parent["mode"] == "greenfield"
                assert detail_parent["token_limit"] == 150000
                assert detail_parent["cost_limit"] == 3.5
                assert detail_parent["max_rounds"] == 4
                assert detail_parent["parent_run_id"] is None

                # 2. Reject clone while parent is still RUNNING (status 400)
                child_payload = {
                    "goal": "Build Distributed Cache (retry)",
                    "requirements": ["In-memory LRU eviction", "Replication over TCP"],
                    "parent_run_id": parent_id,
                }
                res_active = client.post("/api/runs", json=child_payload)
                assert res_active.status_code == 400
                assert "only terminal runs can be cloned" in res_active.json()["detail"]

                # 3. Reject non-existent parent_run_id (status 404)
                bad_payload = {
                    "goal": "Nonexistent parent clone",
                    "requirements": ["Req 1"],
                    "parent_run_id": "RUN-DOES-NOT-EXIST",
                }
                res_not_found = client.post("/api/runs", json=bad_payload)
                assert res_not_found.status_code == 404
                assert "RUN-DOES-NOT-EXIST not found" in res_not_found.json()["detail"]

                # 4. Cancel parent run to transition into terminal state
                client.post(f"/api/runs/{parent_id}/cancel", json={"reason": "Parent cancelled for retry"})
                parent_before = client.get(f"/api/runs/{parent_id}").json()
                assert parent_before["status"] == "CANCELLED"
                events_before = app.state.store.events(parent_id)

                # 5. Successfully clone from cancelled parent run
                res_child = client.post("/api/runs", json=child_payload)
                assert res_child.status_code == 202
                child_id = res_child.json()["run_id"]

                # Verify child has lineage linked
                child_detail = client.get(f"/api/runs/{child_id}").json()
                assert child_detail["parent_run_id"] == parent_id
                assert child_detail["goal"] == "Build Distributed Cache (retry)"

                # 6. Verify parent run immutability
                parent_after = client.get(f"/api/runs/{parent_id}").json()
                assert parent_after["status"] == parent_before["status"]
                assert parent_after["revision"] == parent_before["revision"]
                assert parent_after["stop_reason"] == parent_before["stop_reason"]
                events_after = app.state.store.events(parent_id)
                assert len(events_after) == len(events_before)
        finally:
            app.state.store.close()


def _stage_run_for_resume(app, client, run_id: str) -> None:
    """Moves a run into WAITING_FOR_INPUT via a blocking question and answers it."""
    from astra_multi.domain.models import Question
    from astra_multi.orchestration.controller import WorkflowController

    store = app.state.store
    req_id = store.load(run_id).task.requirements[0].id
    lease = store.acquire(run_id, owner="test", ttl=30)
    ctrl = WorkflowController(store, lease, actor="test")
    q = Question(
        id="Q-001",
        run_id=run_id,
        text="Which database should we use?",
        blocking=True,
        requirement_ids=[req_id],
    )
    ctrl.ask_question(q)
    current_phase = ctrl.get_state().run.phase
    ctrl.transition_phase(current_phase, RunStatus.WAITING_FOR_INPUT, reason="Waiting for clarification")
    store.release(lease)

    res_ans = client.post(f"/api/runs/{run_id}/answers", json={
        "question_id": "Q-001",
        "answer": "Use PostgreSQL 16",
        "expected_revision": client.get(f"/api/runs/{run_id}").json()["revision"],
    })
    assert res_ans.status_code == 200


def test_api_resume_passes_saved_max_rounds():
    """C-2: resuming a run must reuse the max_rounds saved at creation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "api.db"
        art_path = Path(tmpdir) / "artifacts"
        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=True)
        try:
            start_calls = []

            def _spy_start(run_id, max_rounds=2):
                start_calls.append({"run_id": run_id, "max_rounds": max_rounds})

            app.state.worker.start_run = _spy_start

            with TestClient(app) as client:
                res = client.post("/api/runs", json={
                    "goal": "Resume Keeps Max Rounds",
                    "requirements": ["Req M1"],
                    "max_rounds": 5,
                })
                assert res.status_code == 202
                run_id = res.json()["run_id"]

                # Creation itself must have received max_rounds=5
                assert start_calls == [{"run_id": run_id, "max_rounds": 5}]

                _stage_run_for_resume(app, client, run_id)

                res_resume = client.post(f"/api/runs/{run_id}/resume")
                assert res_resume.status_code == 200
                assert res_resume.json()["status"] == "RUNNING"

                # Resume must pass the saved max_rounds=5 to the worker
                assert len(start_calls) == 2
                assert start_calls[-1] == {"run_id": run_id, "max_rounds": 5}
        finally:
            app.state.store.close()


def test_api_resume_without_saved_max_rounds_defaults_to_2():
    """C-2: legacy runs without persisted max_rounds resume with the default of 2."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "api.db"
        art_path = Path(tmpdir) / "artifacts"
        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=True)
        try:
            start_calls = []

            def _spy_start(run_id, max_rounds=2):
                start_calls.append({"run_id": run_id, "max_rounds": max_rounds})

            app.state.worker.start_run = _spy_start

            with TestClient(app) as client:
                res = client.post("/api/runs", json={
                    "goal": "Legacy Resume Default Rounds",
                    "requirements": ["Req L1"],
                })
                assert res.status_code == 202
                run_id = res.json()["run_id"]

                # Simulate a legacy run created before max_rounds was persisted
                (art_path / "metadata" / f"{run_id}.json").unlink()

                _stage_run_for_resume(app, client, run_id)

                res_resume = client.post(f"/api/runs/{run_id}/resume")
                assert res_resume.status_code == 200
                assert res_resume.json()["status"] == "RUNNING"

                # Worker default of 2 must be preserved
                assert start_calls[-1] == {"run_id": run_id, "max_rounds": 2}
        finally:
            app.state.store.close()


