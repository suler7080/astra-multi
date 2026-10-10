import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest

from astra_multi.domain.commands import AddRecord, CommitPlan, TransitionRun
from astra_multi.domain.fixtures import sample_plan, sample_state
from astra_multi.domain.models import (
    ArtifactRef,
    Evidence,
    RunPhase,
    RunStatus,
    utc_now,
)
from astra_multi.domain.policies import (
    InvalidState,
    LeaseLost,
    OperationConflict,
    RevisionConflict,
)
from astra_multi.domain.repositories import RunRepository
from astra_multi.persistence import FileArtifactStore, SQLiteStore
from astra_multi.persistence_demo import write_example


def create(store):
    state = sample_state()
    store.create(state.task, state.run)
    return state, store.acquire(state.run.id, "worker")


def plan_command(state):
    return CommitPlan(
        expected_revision=state.run.revision,
        node="revise",
        logical_operation_id="plan-1",
        actor="planner",
        plan=sample_plan(state),
    )


def test_atomic_idempotency_event_sequence_and_restart(tmp_path):
    path = tmp_path / "domain.sqlite"
    with SQLiteStore(path) as store:
        state, lease = create(store)
        command = plan_command(state)
        operation = store.commit(state.run.id, command, lease)
        assert store.commit(state.run.id, command, lease) == operation
        assert len(store.load(state.run.id).plans) == 1
        assert [event.sequence for event in store.events(state.run.id)] == [1, 2]
        assert store.events(state.run.id, after=1)[0].revision == operation.revision
    with SQLiteStore(path) as store:
        assert store.operation(state.run.id, "revise", "plan-1") == operation
        assert store.load(state.run.id).run.revision == 2


@pytest.mark.parametrize("point", ["after_mutation", "after_event", "after_operation"])
def test_transaction_failure_rolls_back_entire_write(tmp_path, point):
    def fault(actual):
        if actual == point:
            raise OSError("injected transaction failure")

    with SQLiteStore(tmp_path / "domain.sqlite", fault=fault) as store:
        state, lease = create(store)
        with pytest.raises(OSError, match="injected"):
            store.commit(state.run.id, plan_command(state), lease)
        assert store.load(state.run.id) == state
        assert len(store.events(state.run.id)) == 1
        assert store.operation(state.run.id, "revise", "plan-1") is None


def test_stale_and_operation_collision_write_nothing(tmp_path):
    with SQLiteStore(tmp_path / "domain.sqlite") as store:
        state, lease = create(store)
        command = plan_command(state)
        store.commit(state.run.id, command, lease)
        with pytest.raises(RevisionConflict):
            store.commit(
                state.run.id,
                command.model_copy(update={"logical_operation_id": "stale"}),
                lease,
            )
        with pytest.raises(OperationConflict):
            store.commit(
                state.run.id, command.model_copy(update={"actor": "other"}), lease
            )
        assert len(store.events(state.run.id)) == 2
        assert store.operation(state.run.id, "revise", "stale") is None


def evidence_command(state, ref):
    return AddRecord(
        expected_revision=1,
        node="verify",
        logical_operation_id="evidence",
        actor="controller",
        record=Evidence(
            id="EVID",
            run_id=state.run.id,
            source_type="document",
            locator="artifact",
            content_hash=ref.content_hash,
            captured_at=utc_now(),
            snapshot_id=None,
            artifact=ref,
        ),
    )


def test_artifact_restart_and_corruption_detection(tmp_path):
    with SQLiteStore(tmp_path / "domain.sqlite") as store:
        state, lease = create(store)
        ref = store.artifacts.put(b"large evidence")
        store.commit(state.run.id, evidence_command(state, ref), lease)
    with SQLiteStore(tmp_path / "domain.sqlite") as store:
        persisted = store.load(state.run.id).evidence[0].artifact
        assert store.artifacts.read(persisted) == b"large evidence"
        (tmp_path / "artifacts" / ref.content_hash).write_bytes(b"corrupted")
        with pytest.raises(ValueError, match="mismatch"):
            store.artifacts.read(ref)


def test_missing_artifact_creates_no_reference(tmp_path):
    with SQLiteStore(tmp_path / "domain.sqlite") as store:
        state, lease = create(store)
        ref = ArtifactRef(content_hash="a" * 64, size=10)
        with pytest.raises(FileNotFoundError):
            store.commit(state.run.id, evidence_command(state, ref), lease)
        assert store.load(state.run.id).evidence == []
        assert len(store.events(state.run.id)) == 1


def test_artifact_failed_write_leaves_no_file(tmp_path, monkeypatch):
    artifacts = FileArtifactStore(tmp_path / "artifacts")

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr("astra_multi.persistence.artifacts.os.replace", fail)
    with pytest.raises(OSError, match="disk full"):
        artifacts.put(b"data")
    assert list(artifacts.root.iterdir()) == []


def test_migration_new_existing_and_future_schema(tmp_path):
    path = tmp_path / "domain.sqlite"
    with SQLiteStore(path) as store:
        assert store.connection.execute("PRAGMA user_version").fetchone()[0] == 1
        state, _ = create(store)
    with SQLiteStore(path) as store:
        assert store.load(state.run.id) == state
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version=99")
    with pytest.raises(ValueError, match="newer"):
        SQLiteStore(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 99


def test_heartbeat_stale_takeover_and_expired_writer_fencing(tmp_path):
    now = utc_now()
    path = tmp_path / "domain.sqlite"
    with (
        SQLiteStore(path, clock=lambda: now) as old,
        SQLiteStore(path, clock=lambda: now) as new,
    ):
        state, lease = create(old)
        now += timedelta(seconds=10)
        renewed = old.heartbeat(lease)
        assert renewed.expires_at > lease.expires_at
        with pytest.raises(LeaseLost):
            new.acquire(state.run.id, "other")
        now += timedelta(seconds=31)
        with pytest.raises(LeaseLost):
            old.heartbeat(lease)
        replacement = new.acquire(state.run.id, "other")
        assert replacement.epoch == lease.epoch + 1
        with pytest.raises(LeaseLost):
            old.commit(state.run.id, plan_command(state), lease)
        new.commit(state.run.id, plan_command(state), replacement)
        with pytest.raises(LeaseLost):
            old.release(lease)


def test_lease_expiration_during_transaction_rolls_back(tmp_path):
    now = utc_now()

    def fault(point):
        nonlocal now
        if point == "after_operation":
            now += timedelta(seconds=31)

    with SQLiteStore(
        tmp_path / "domain.sqlite", clock=lambda: now, fault=fault
    ) as store:
        state, lease = create(store)
        with pytest.raises(LeaseLost):
            store.commit(state.run.id, plan_command(state), lease)
        assert store.load(state.run.id).run.revision == 1
        assert len(store.events(state.run.id)) == 1


def test_two_writers_contend_only_one_lease_wins(tmp_path):
    path = tmp_path / "domain.sqlite"
    with SQLiteStore(path) as store:
        state = sample_state()
        store.create(state.task, state.run)
    barrier = Barrier(2)

    def contend(owner):
        with SQLiteStore(path) as store:
            barrier.wait(timeout=10)
            try:
                lease = store.acquire(state.run.id, owner)
                store.commit(state.run.id, plan_command(state), lease)
                return "won"
            except LeaseLost:
                return "lost"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(contend, ["one", "two"])) == ["lost", "won"]
    with SQLiteStore(path) as store:
        assert len(store.load(state.run.id).plans) == 1


def test_terminal_acquire_resume_and_final_are_rejected(tmp_path):
    with SQLiteStore(tmp_path / "domain.sqlite") as store:
        state, lease = create(store)
        with pytest.raises(InvalidState):
            store.commit(
                state.run.id,
                TransitionRun(
                    expected_revision=1,
                    node="gate",
                    logical_operation_id="final",
                    actor="controller",
                    phase=RunPhase.EXPORT,
                    status=RunStatus.FINAL,
                ),
                lease,
            )
        store.commit(
            state.run.id,
            TransitionRun(
                expected_revision=1,
                node="stop",
                logical_operation_id="cancel",
                actor="user",
                phase=RunPhase.INTAKE,
                status=RunStatus.CANCELLED,
                reason="User stopped",
            ),
            lease,
        )
        store.release(lease)
        with pytest.raises(InvalidState):
            store.acquire(state.run.id, "new")


def test_partial_run_can_be_acquired_by_quality_service_and_finalized(tmp_path):
    with SQLiteStore(tmp_path / "domain.sqlite") as store:
        state, lease = create(store)
        # Transition run to PARTIAL in current phase
        store.commit(
            state.run.id,
            TransitionRun(
                expected_revision=1,
                node="export",
                logical_operation_id="export-partial",
                actor="worker",
                phase=state.run.phase,
                status=RunStatus.PARTIAL,
                reason="MVP candidate generated (awaiting P4 quality certification)",
            ),
            lease,
        )
        store.release(lease)

        # Non-quality owner is rejected
        with pytest.raises(InvalidState, match="cannot acquire a terminal run"):
            store.acquire(state.run.id, "worker")

        # quality-service is allowed to acquire PARTIAL run
        quality_lease = store.acquire(state.run.id, "quality-service", ttl=30)
        assert quality_lease.owner == "quality-service"

        # P4 quality service can transition PARTIAL run to FINAL
        loaded = store.load(state.run.id)
        store.commit(
            state.run.id,
            TransitionRun(
                expected_revision=loaded.run.revision,
                node="gate",
                logical_operation_id="finalize",
                actor="P4-quality-service",
                phase=loaded.run.phase,
                status=RunStatus.FINAL,
                reason="Certified final plan",
            ),
            quality_lease,
        )
        store.release(quality_lease)

        final_state = store.load(state.run.id)
        assert final_state.run.status == RunStatus.FINAL
        assert final_state.run.phase == state.run.phase

        # Once FINAL, even quality-service cannot re-acquire
        with pytest.raises(InvalidState, match="cannot acquire a terminal run"):
            store.acquire(state.run.id, "quality-service")


def test_sample_client_uses_repository_protocol_and_reopens(tmp_path):
    path = tmp_path / "domain.sqlite"
    with SQLiteStore(path) as store:
        repository: RunRepository = store
        run_id = write_example(repository, store)
    with SQLiteStore(path) as store:
        state = store.load(run_id)
        assert state.run.revision == 6
        assert len(state.plans) == 1
        assert state.issues[0].status.value == "resolved"
        assert len(state.issues[0].history) == 4
        assert len(store.events(run_id)) == 6
