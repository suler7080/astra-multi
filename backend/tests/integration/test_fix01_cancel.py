"""Tests for FIX-01: cancel_run succeeds when worker holds lease and stops background worker."""

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from astra_multi.api.app import create_app
from astra_multi.domain.commands import TransitionRun
from astra_multi.domain.models import RunPhase, RunStatus
from astra_multi.domain.policies import LeaseLost
from astra_multi.persistence.sqlite import SQLiteStore


def test_cancel_run_succeeds_when_worker_holds_lease():
    """FIX-01: POST /api/runs/{id}/cancel returns 200 and cancels run even when worker lease is active."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_cancel.db"
        art_path = Path(tmpdir) / "artifacts"
        art_path.mkdir(parents=True, exist_ok=True)

        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)
        client = TestClient(app, raise_server_exceptions=False)
        store: SQLiteStore = app.state.store

        try:
            # 1. Create run
            create_res = client.post(
                "/api/runs",
                json={
                    "goal": "Verify cancel when worker lease is held",
                    "requirements": ["REQ-1"],
                },
            )
            assert create_res.status_code == 202
            run_id = create_res.json()["run_id"]

            # 2. Worker acquires lease (TTL 60s)
            worker_lease = store.acquire(run_id, owner="worker-agent", ttl=60)
            assert worker_lease.owner == "worker-agent"
            assert worker_lease.epoch == 1

            # 3. User cancels run via API
            cancel_res = client.post(
                f"/api/runs/{run_id}/cancel",
                json={"reason": "User clicked cancel in UI"},
            )

            assert cancel_res.status_code == 200
            res_json = cancel_res.json()
            assert res_json["status"] == "CANCELLED"
            assert res_json["run_id"] == run_id
            assert "User clicked cancel in UI" in res_json["message"]

            # 4. Check DB status: CANCELLED
            state_after = store.load(run_id)
            assert state_after.run.status == RunStatus.CANCELLED
            assert state_after.run.stop_reason == "User clicked cancel in UI"

            # 5. Check fencing: worker lease epoch is stale, attempts to commit fail with LeaseLost
            cmd = TransitionRun(
                expected_revision=state_after.run.revision,
                node="investigate",
                logical_operation_id=f"phase-investigate-{state_after.run.revision}",
                actor="worker-agent",
                phase=RunPhase.INVESTIGATE,
                status=RunStatus.RUNNING,
            )
            with pytest.raises(LeaseLost):
                store.commit(run_id, cmd, worker_lease)

            # 6. Heartbeat on old worker lease also fails with LeaseLost
            with pytest.raises(LeaseLost):
                store.heartbeat(worker_lease)
        finally:
            store.close()


def test_cancel_run_stops_active_background_worker_task():
    """FIX-01: Background worker task is cleanly stopped upon cancellation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_cancel_worker.db"
        art_path = Path(tmpdir) / "artifacts"
        art_path.mkdir(parents=True, exist_ok=True)

        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=True)
        client = TestClient(app, raise_server_exceptions=False)
        store: SQLiteStore = app.state.store
        worker = app.state.worker

        try:
            # 1. Create run with worker auto-started
            create_res = client.post(
                "/api/runs",
                json={
                    "goal": "Verify active worker task stopping",
                    "requirements": ["REQ-1"],
                },
            )
            assert create_res.status_code == 202
            run_id = create_res.json()["run_id"]

            # 2. Cancel run
            cancel_res = client.post(
                f"/api/runs/{run_id}/cancel",
                json={"reason": "Stopping active worker run"},
            )

            assert cancel_res.status_code == 200
            assert cancel_res.json()["status"] == "CANCELLED"

            # 3. Worker task is no longer active
            assert not worker.is_running(run_id)

            # 4. Status in DB is CANCELLED
            state = store.load(run_id)
            assert state.run.status == RunStatus.CANCELLED
        finally:
            store.close()


def test_cancel_run_idempotent():
    """Cancelling an already cancelled run returns 200 OK with CANCELLED status."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_cancel_idem.db"
        art_path = Path(tmpdir) / "artifacts"
        art_path.mkdir(parents=True, exist_ok=True)

        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)
        client = TestClient(app, raise_server_exceptions=False)
        store: SQLiteStore = app.state.store

        try:
            create_res = client.post(
                "/api/runs",
                json={"goal": "Test idempotency", "requirements": ["REQ-1"]},
            )
            run_id = create_res.json()["run_id"]

            res1 = client.post(f"/api/runs/{run_id}/cancel", json={"reason": "First cancel"})
            assert res1.status_code == 200
            assert res1.json()["status"] == "CANCELLED"

            res2 = client.post(f"/api/runs/{run_id}/cancel", json={"reason": "Second cancel"})
            assert res2.status_code == 200
            assert res2.json()["status"] == "CANCELLED"
            assert "already cancelled" in res2.json()["message"]
        finally:
            store.close()


def test_cancel_run_not_found():
    """Cancelling a non-existent run returns 404."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_cancel_404.db"
        art_path = Path(tmpdir) / "artifacts"
        art_path.mkdir(parents=True, exist_ok=True)

        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)
        client = TestClient(app, raise_server_exceptions=False)
        try:
            res = client.post("/api/runs/NONEXISTENT/cancel", json={"reason": "Cancel"})
            assert res.status_code == 404
        finally:
            app.state.store.close()


def test_cancel_run_terminal_state():
    """Cancelling a run that is already in terminal status (e.g. FAILED) returns 400."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_cancel_term.db"
        art_path = Path(tmpdir) / "artifacts"
        art_path.mkdir(parents=True, exist_ok=True)

        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)
        client = TestClient(app, raise_server_exceptions=False)
        store: SQLiteStore = app.state.store

        try:
            create_res = client.post(
                "/api/runs",
                json={"goal": "Terminal test", "requirements": ["REQ-1"]},
            )
            run_id = create_res.json()["run_id"]

            # Manually transition run to FAILED
            lease = store.acquire(run_id, owner="test", ttl=30)
            state = store.load(run_id)
            cmd = TransitionRun(
                expected_revision=state.run.revision,
                node="test-fail",
                logical_operation_id=f"phase-intake-fail-{state.run.revision}",
                actor="test",
                phase=state.run.phase,
                status=RunStatus.FAILED,
                reason="Failed in testing",
            )
            store.commit(run_id, cmd, lease)
            store.release(lease)

            # Attempt to cancel FAILED run
            res = client.post(f"/api/runs/{run_id}/cancel", json={"reason": "Cancel failed run"})
            assert res.status_code == 400
            assert "Cannot cancel run in terminal status" in res.json()["detail"]
        finally:
            store.close()


def test_sqlite_acquire_force_flag():
    """Unit test: SQLiteStore.acquire force parameter behavior and epoch fencing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_store_force.db"
        art_path = Path(tmpdir) / "artifacts"
        art_path.mkdir(parents=True, exist_ok=True)

        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)
        client = TestClient(app, raise_server_exceptions=False)
        store: SQLiteStore = app.state.store

        try:
            create_res = client.post(
                "/api/runs",
                json={"goal": "Lease force test", "requirements": ["REQ-1"]},
            )
            run_id = create_res.json()["run_id"]

            lease1 = store.acquire(run_id, owner="worker-1", ttl=60)
            assert lease1.epoch == 1
            assert lease1.owner == "worker-1"

            # acquire without force while active raises LeaseLost
            with pytest.raises(LeaseLost, match="run already leased"):
                store.acquire(run_id, owner="worker-2", ttl=60, force=False)

            # acquire with force=True succeeds and increments epoch
            lease2 = store.acquire(run_id, owner="worker-2", ttl=60, force=True)
            assert lease2.epoch == 2
            assert lease2.owner == "worker-2"
            assert lease2.token != lease1.token

            # old lease cannot be heartbeated or checked
            with pytest.raises(LeaseLost):
                store.heartbeat(lease1)

            # new lease can be heartbeated
            renewed = store.heartbeat(lease2)
            assert renewed.epoch == 2
        finally:
            store.close()
