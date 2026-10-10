"""Tests for FIX-06: Lightweight SSE status polling without full state deserialization.

Verifies:
1. SQLiteStore.get_run_status_info returns accurate status, phase, and stop_reason.
2. RunWorker.event_stream polls terminal status without calling store.load (0 full deserializations).
3. RunWorker.event_stream streams all events and finishes with run_completed event.
4. RunWorker.event_stream terminates safely when a run does not exist or is deleted.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from astra_multi.api.worker import RunWorker
from astra_multi.domain.commands import TransitionRun
from astra_multi.domain.fixtures import sample_state
from astra_multi.domain.models import RunPhase, RunStatus
from astra_multi.persistence.sqlite import SQLiteStore


def test_get_run_status_info_returns_accurate_fields():
    """SQLiteStore.get_run_status_info extracts status, phase, and stop_reason directly from SQLite."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_fix06_status.db"
        with SQLiteStore(db_path) as store:
            state = sample_state()
            store.create(state.task, state.run)
            lease = store.acquire(state.run.id, owner="worker", ttl=60)

            # Initially RUNNING / INTAKE
            status_info = store.get_run_status_info(state.run.id)
            assert status_info is not None
            status, phase, stop_reason = status_info
            assert status.lower() == "running"
            assert phase.lower() == "intake"
            assert stop_reason is None

            # Transition to FINAL with stop_reason
            cmd = TransitionRun(
                expected_revision=state.run.revision,
                node="finalize",
                logical_operation_id="trans-final-1",
                actor="quality-service",
                phase=state.run.phase,
                status=RunStatus.FINAL,
                reason="Goal achieved successfully",
            )
            store.commit(state.run.id, cmd, lease)

            # Check status info again
            status_info_after = store.get_run_status_info(state.run.id)
            assert status_info_after is not None
            status_2, phase_2, stop_reason_2 = status_info_after
            assert status_2.lower() == "final"
            assert phase_2.lower() == "intake"
            assert stop_reason_2 == "Goal achieved successfully"


@pytest.mark.asyncio
async def test_event_stream_does_not_call_store_load():
    """event_stream avoids store.load completely during polling, preventing costly JSON deserialization."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_fix06_no_load.db"
        with SQLiteStore(db_path) as store:
            state = sample_state()
            store.create(state.task, state.run)
            lease = store.acquire(state.run.id, owner="worker", ttl=60)

            # Transition run to terminal status
            cmd = TransitionRun(
                expected_revision=state.run.revision,
                node="finalize",
                logical_operation_id="trans-terminal-1",
                actor="quality-service",
                phase=state.run.phase,
                status=RunStatus.FINAL,
                reason="Finished",
            )
            store.commit(state.run.id, cmd, lease)

            # Track calls to store.load
            orig_load = store.load
            load_calls = 0

            def counted_load(run_id: str):
                nonlocal load_calls
                load_calls += 1
                return orig_load(run_id)

            store.load = counted_load

            worker = RunWorker(store=store)
            collected_events = []
            async for ev in worker.event_stream(state.run.id):
                collected_events.append(ev)

            # Crucial assertion: store.load was never called
            assert load_calls == 0
            # Confirm run_completed was delivered
            assert any(ev["event"] == "run_completed" for ev in collected_events)
            completed_ev = next(ev for ev in collected_events if ev["event"] == "run_completed")
            assert completed_ev["data"]["status"] == "FINAL"
            assert completed_ev["data"]["phase"] == "INTAKE"
            assert completed_ev["data"]["stop_reason"] == "Finished"


@pytest.mark.asyncio
async def test_event_stream_handles_nonexistent_run_safely():
    """event_stream safely exits without throwing unhandled exceptions when run is not found."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_fix06_nonexistent.db"
        with SQLiteStore(db_path) as store:
            worker = RunWorker(store=store)
            collected = []
            async for ev in worker.event_stream("RUN-NONEXISTENT"):
                collected.append(ev)
            assert len(collected) == 0
