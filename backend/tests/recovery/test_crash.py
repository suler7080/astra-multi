import json
import selectors
import subprocess
import sys
from datetime import timedelta

import pytest

from astra_multi.domain.commands import CommitPlan
from astra_multi.domain.fixtures import sample_plan, sample_state
from astra_multi.domain.models import CheckpointRef, Lease, utc_now
from astra_multi.domain.policies import LeaseLost, RevisionConflict
from astra_multi.persistence import CheckpointBridge, SQLiteStore


def start_worker(workspace, mode, *args):
    return subprocess.Popen(
        [sys.executable, "-m", "tests.recovery.worker", str(workspace), mode, *args],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def wait_line(process):
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        if not selector.select(timeout=20):
            process.kill()
            output, errors = process.communicate(timeout=10)
            pytest.fail(f"worker did not reach boundary: {output} {errors}")
    line = process.stdout.readline().strip()
    if not line:
        output, errors = process.communicate(timeout=10)
        pytest.fail(f"worker exited before boundary: {output} {errors}")
    return line


@pytest.mark.parametrize(
    "boundary",
    ["after_mutation", "after_event", "after_operation", "after_domain_commit"],
)
def test_kill_restart_atomicity_and_domain_ahead_of_checkpoint(tmp_path, boundary):
    with SQLiteStore(tmp_path / "domain.sqlite") as store:
        state = sample_state()
        store.create(state.task, state.run)
        lease = store.acquire(state.run.id, "worker", ttl=60)
        checkpoint = CheckpointBridge(store).reference(state.run.id)
        command = CommitPlan(
            expected_revision=1,
            node="revise",
            logical_operation_id="candidate-1",
            actor="planner",
            plan=sample_plan(state),
        )
        (tmp_path / "lease.json").write_text(lease.model_dump_json())
        (tmp_path / "command.json").write_text(command.model_dump_json())
    worker = start_worker(tmp_path, boundary)
    try:
        assert wait_line(worker) == (
            "committed" if boundary == "after_domain_commit" else "uncommitted"
        )
        worker.kill()
        worker.communicate(timeout=10)
    finally:
        if worker.poll() is None:
            worker.kill()
            worker.communicate(timeout=10)
    with SQLiteStore(tmp_path / "domain.sqlite") as store:
        committed = boundary == "after_domain_commit"
        assert store.load(state.run.id).run.revision == (2 if committed else 1)
        assert len(store.events(state.run.id)) == (2 if committed else 1)
        assert CheckpointBridge(store).load(checkpoint).run.revision == (
            2 if committed else 1
        )
    restarted = start_worker(tmp_path, "restart")
    output, errors = restarted.communicate(timeout=30)
    assert restarted.returncode == 0, errors
    restored = CheckpointRef.model_validate_json(output.strip())
    assert restored.revision == 2
    with SQLiteStore(tmp_path / "domain.sqlite") as store:
        assert len(store.load(state.run.id).plans) == 1
        assert len(store.events(state.run.id)) == 2
        assert store.operation(state.run.id, "revise", "candidate-1").revision == 2


def test_subprocess_lease_contention_and_takeover_fences_old_writer(tmp_path):
    with SQLiteStore(tmp_path / "domain.sqlite") as store:
        state = sample_state()
        store.create(state.task, state.run)
    workers = [start_worker(tmp_path, "contend", owner) for owner in ("one", "two")]
    try:
        for worker in workers:
            assert wait_line(worker) == "ready"
        for worker in workers:
            worker.stdin.write("go\n")
            worker.stdin.flush()
        results = []
        for worker in workers:
            output, errors = worker.communicate(timeout=20)
            assert worker.returncode == 0, errors
            results.append(json.loads(output.strip()))
        assert sum("winner" in result for result in results) == 1
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
                worker.communicate(timeout=10)
    with SQLiteStore(tmp_path / "domain.sqlite") as store:
        lease_row = store.connection.execute(
            "SELECT owner, token, epoch, expires_at FROM leases"
        ).fetchone()
        old = Lease(
            run_id=state.run.id,
            owner=lease_row[0],
            token=lease_row[1],
            epoch=lease_row[2],
            expires_at=lease_row[3],
        )
    now = utc_now() + timedelta(seconds=61)
    with SQLiteStore(tmp_path / "domain.sqlite", clock=lambda: now) as store:
        replacement = store.acquire(state.run.id, "replacement")
        command = CommitPlan(
            expected_revision=1,
            node="revise",
            logical_operation_id="candidate-1",
            actor="planner",
            plan=sample_plan(state),
        )
        with pytest.raises(LeaseLost):
            store.commit(state.run.id, command, old)
        store.commit(state.run.id, command, replacement)
        assert replacement.epoch == old.epoch + 1


def test_checkpoint_rejects_unknown_or_future_references(tmp_path):
    with SQLiteStore(tmp_path / "domain.sqlite") as store:
        state = sample_state()
        store.create(state.task, state.run)
        bridge = CheckpointBridge(store)
        checkpoint = bridge.reference(state.run.id)
        for change in (
            {"revision": 2},
            {"task_revision": 2},
            {"task_id": "OTHER"},
            {"plan_id": "OTHER"},
        ):
            with pytest.raises(RevisionConflict):
                bridge.load(checkpoint.model_copy(update=change))
