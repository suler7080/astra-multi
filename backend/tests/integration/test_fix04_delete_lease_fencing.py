"""Tests for FIX-04: Lease fencing protection during run deletion.

Verifies:
1. SQLiteStore.delete rejects deletion of active leased runs without a valid lease or force=True.
2. SQLiteStore.delete succeeds when caller presents the valid lease.
3. SQLiteStore.delete succeeds when caller passes force=True (admin override).
4. SQLiteStore.delete succeeds for unleased or released runs.
5. API endpoint DELETE /api/runs/{run_id} returns 409 Conflict when run is actively leased,
   and succeeds when ?force=true is provided.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from astra_multi.api.app import create_app
from astra_multi.domain.fixtures import sample_state
from astra_multi.domain.models import Lease
from astra_multi.domain.policies import LeaseLost
from astra_multi.persistence.sqlite import SQLiteStore


def test_delete_leased_run_without_force_raises_leaselost():
    """Attempting to delete a run currently leased by a worker raises LeaseLost and leaves data intact."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_delete_fencing.db"
        with SQLiteStore(db_path) as store:
            state = sample_state()
            store.create(state.task, state.run)
            _lease = store.acquire(state.run.id, owner="worker-primary", ttl=120)

            # Calling delete without lease and without force must raise LeaseLost
            with pytest.raises(LeaseLost) as exc_info:
                store.delete(state.run.id)
            assert "worker-primary" in str(exc_info.value)

            # Run still exists intact in store
            loaded = store.load(state.run.id)
            assert loaded.run.id == state.run.id


def test_delete_leased_run_with_valid_lease_succeeds():
    """Holding the valid lease allows deleting the run without force."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_delete_valid_lease.db"
        with SQLiteStore(db_path) as store:
            state = sample_state()
            store.create(state.task, state.run)
            lease = store.acquire(state.run.id, owner="worker-primary", ttl=120)

            # Calling delete with the active lease succeeds
            store.delete(state.run.id, lease=lease)

            # Run is permanently removed
            with pytest.raises(KeyError):
                store.load(state.run.id)


def test_delete_leased_run_with_mismatched_lease_fails():
    """Attempting to delete with a forged or mismatched lease raises LeaseLost."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_delete_mismatched.db"
        with SQLiteStore(db_path) as store:
            state = sample_state()
            store.create(state.task, state.run)
            store.acquire(state.run.id, owner="worker-primary", ttl=120)

            bogus_lease = Lease(
                run_id=state.run.id,
                owner="rogue-worker",
                token=str(uuid4()),
                epoch=1,
                expires_at=store.clock(),
            )

            with pytest.raises(LeaseLost):
                store.delete(state.run.id, lease=bogus_lease)

            # Run remains intact
            assert store.load(state.run.id).run.id == state.run.id


def test_delete_leased_run_with_force_true_succeeds():
    """Admin override with force=True deletes an actively leased run."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_delete_force.db"
        with SQLiteStore(db_path) as store:
            state = sample_state()
            store.create(state.task, state.run)
            store.acquire(state.run.id, owner="worker-primary", ttl=120)

            # Force delete overrides active lease
            store.delete(state.run.id, force=True)

            with pytest.raises(KeyError):
                store.load(state.run.id)


def test_delete_released_run_succeeds():
    """Deleting a run whose lease has been released succeeds normally."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_delete_released.db"
        with SQLiteStore(db_path) as store:
            state = sample_state()
            store.create(state.task, state.run)
            lease = store.acquire(state.run.id, owner="worker-primary", ttl=120)
            store.release(lease)

            # Released run has no active lease (expires_at <= now)
            store.delete(state.run.id)

            with pytest.raises(KeyError):
                store.load(state.run.id)


def test_api_delete_leased_run_conflicts_and_force_deletes():
    """DELETE /api/runs/{run_id} returns 409 when actively leased and 200 with ?force=true."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_api_delete.db"
        art_path = Path(tmpdir) / "artifacts"
        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)
        with TestClient(app) as client:
            test_store = app.state.store

            # Create run via API
            create_res = client.post(
                "/api/runs",
                json={"goal": "Test Delete Fencing", "requirements": ["Requirement 1"]},
            )
            assert create_res.status_code == 202
            run_id = create_res.json()["run_id"]

            # Simulate an external background worker acquiring a lease
            test_store.acquire(run_id, owner="external-worker-node", ttl=300)

            # Attempt normal DELETE without force -> must fail with 409 Conflict
            del_res = client.delete(f"/api/runs/{run_id}")
            assert del_res.status_code == 409
            assert "cannot be deleted" in del_res.json()["detail"] or "active" in del_res.json()["detail"]

            # Run still exists in store
            assert test_store.load(run_id).run.id == run_id

            # Attempt DELETE with force=true -> must succeed with 200 OK
            del_force_res = client.delete(f"/api/runs/{run_id}?force=true")
            assert del_force_res.status_code == 200
            assert del_force_res.json()["run_id"] == run_id

            # Run is now gone
            with pytest.raises(KeyError):
                test_store.load(run_id)
