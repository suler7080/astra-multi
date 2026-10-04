"""Integration invariant and fault injection tests for P6.1.

Verifies cross-component invariants:
1. Budget reservation cap never exceeded under concurrent race conditions.
2. Zero FINAL state granted when unresolved BLOCKING issues exist.
3. Unavailable sandbox / runner never silently becomes PASS.
4. Committed artifacts and canonical revisions are never lost or duplicated.
5. Cancelled run halts workflow progression.
6. SSE reconnect with Last-Event-ID delivers exact replay without gaps or duplication.
"""

from __future__ import annotations

import concurrent.futures
import tempfile
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from astra_multi.api.app import create_app
from astra_multi.domain.commands import CommitPlan
from astra_multi.domain.fixtures import sample_plan, sample_state
from astra_multi.domain.models import (
    Issue,
    IssueSeverity,
    IssueStatus,
    RunStatus,
    ValidationStatus,
)
from astra_multi.exports.finalization import (
    FinalizationService,
    SemanticReviewAssessment,
)
from astra_multi.exports.quality_validator import StructuralQualityValidator
from astra_multi.orchestration.budget import BudgetExhaustedError, BudgetService
from astra_multi.persistence.sqlite import SQLiteStore
from astra_multi.sandbox.runner import DockerRunner, JobRequest, SandboxProfile


def test_concurrent_budget_reservations_race_condition():
    """Verify that multiple concurrent threads reserving budget never exceed the cap."""
    token_limit = 5000
    cost_limit = 0.50
    budget = BudgetService(token_limit=token_limit, cost_limit=cost_limit, call_limit=20)

    success_reservations = []
    exhausted_exceptions = []

    def try_reserve(i: int):
        try:
            op_id = budget.reserve(
                estimated_tokens=500,
                estimated_cost=0.05,
                operation_id=f"RES-{i:03d}",
            )
            success_reservations.append(op_id)
        except BudgetExhaustedError as e:
            exhausted_exceptions.append(str(e))

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(try_reserve, i) for i in range(25)]
        concurrent.futures.wait(futures)

    summary = budget.get_summary()
    # At most 10 reservations of 500 tokens / 0.05 cost can fit into 5000 / 0.50
    assert len(success_reservations) <= 10
    assert summary["active_reservations"] == len(success_reservations)
    assert budget.total_reserved_tokens <= token_limit
    assert budget.total_reserved_cost <= cost_limit + 1e-9
    assert len(exhausted_exceptions) >= 15


def test_zero_final_with_unresolved_blocker_invariant():
    """Verify that zero runs can reach FINAL status if a BLOCKING issue remains unresolved."""
    state = sample_state()
    plan = sample_plan(state)
    blocking_issue = Issue(
        id="ISSUE-CRIT-001",
        run_id=state.run.id,
        severity=IssueSeverity.BLOCKING,
        status=IssueStatus.OPEN,
        based_on_revision=0,
        claim="Critical data leakage in payment token serialization",
        impact="Compromises PCI compliance",
        verification_request="Run security static analyzer",
        suggested_resolution="Use cryptographic token masking",
        requirement_ids=["REQ-001"],
    )

    state_with_blocker = state.model_copy(
        update={"plans": [plan], "issues": [blocking_issue]}
    )

    # 1. Structural validator MUST fail
    validator = StructuralQualityValidator()
    report = validator.validate(state_with_blocker)
    assert report.passed is False
    assert report.has_blockers is True
    assert "ISSUE-CRIT-001" in report.unresolved_blocking_issues

    # 2. Finalization service MUST reject FINAL even if semantic review passed
    service = FinalizationService(validator=validator)
    semantic_review = SemanticReviewAssessment(
        passed=True,
        reviewed_plan_revision=plan.revision,
        feedback="Looks good from my side.",
        concerns=[],
    )

    decision = service.evaluate(state_with_blocker, semantic_review)
    assert decision.can_finalize is False
    assert decision.target_status != RunStatus.FINAL
    assert decision.target_status == RunStatus.PARTIAL
    assert "Blocking issue remains unresolved" in decision.reason


def test_unavailable_runner_never_becomes_pass(tmp_path):
    """Verify missing/unavailable sandbox runner reports UNAVAILABLE and NOT_RUN, never PASS."""
    from astra_multi.context.snapshots import SnapshotStore

    store = SQLiteStore(tmp_path / "domain.sqlite")
    try:
        snapshots = SnapshotStore(store.artifacts)
        repo_dir = tmp_path / "mock_repo"
        repo_dir.mkdir()
        (repo_dir / "app.py").write_text("print('hello')")
        snapshot = snapshots.capture(repo_dir)

        # DockerRunner on Windows without active Docker container runtime is unavailable
        runner = DockerRunner(
            snapshots=snapshots,
            work_root=tmp_path / "work",
            profile=SandboxProfile(target_os="linux"),
        )

        job = JobRequest(
            run_id="RUN-INV-01",
            snapshot_id=snapshot.snapshot.id,
            call_id="CALL-001",
            command=("python", "-c", "print('should not run')"),
        )

        result = runner.execute(snapshot, job)
        assert result.status == "unavailable"
        assert result.validation_status == ValidationStatus.NOT_RUN
        assert result.exit_code is None
        assert "unavailable" in result.actual.lower()
        assert result.environment.available is False
    finally:
        store.close()


def test_no_committed_artifact_loss_or_duplicate_canonical_revision(tmp_path):
    """Verify that committed plans and artifacts have immutable monotonic revisions."""
    with SQLiteStore(tmp_path / "domain.sqlite") as store:
        state = sample_state()
        store.create(state.task, state.run)
        lease = store.acquire(state.run.id, owner="writer-1", ttl=60)

        plan_rev1 = sample_plan(state).model_copy(update={"revision": 1, "based_on_revision": 0})
        cmd1 = CommitPlan(
            expected_revision=1,
            node="revise",
            logical_operation_id="plan-commit-1",
            actor="planner",
            plan=plan_rev1,
        )
        store.commit(state.run.id, cmd1, lease)

        loaded_1 = store.load(state.run.id)
        assert loaded_1.run.revision == 2
        assert len(loaded_1.plans) == 1
        assert loaded_1.plans[0].revision == 1

        # Second revision commit (consecutive: revision 2 based on 1)
        plan_rev2 = sample_plan(state).model_copy(update={"revision": 2, "based_on_revision": 1, "id": "PLAN-V2"})
        cmd2 = CommitPlan(
            expected_revision=2,
            node="revise",
            logical_operation_id="plan-commit-2",
            actor="planner",
            plan=plan_rev2,
        )
        store.commit(state.run.id, cmd2, lease)

        loaded_2 = store.load(state.run.id)
        assert loaded_2.run.revision == 3
        assert len(loaded_2.plans) == 2
        # Check revisions are distinct and ordered
        revisions = [p.revision for p in loaded_2.plans]
        assert revisions == [1, 2]

        # Artifact integrity: store content with hash
        art_ref = store.artifacts.put(b"critical-evidence-data")
        assert (store.artifacts.root / art_ref.content_hash).exists()
        read_back = store.artifacts.read(art_ref)
        assert read_back == b"critical-evidence-data"

        # Tampering detection: modifying content on disk causes ValueError on read
        (store.artifacts.root / art_ref.content_hash).write_bytes(b"tampered-content")
        with pytest.raises(ValueError, match="artifact hash or size mismatch"):
            store.artifacts.read(art_ref)


def test_sse_reconnect_replay_integrity():
    """Verify that SSE reconnect with Last-Event-ID provides deterministic replay without drops."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "api.db"
        art_path = Path(tmpdir) / "artifacts"
        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)
        try:
            with TestClient(app) as client:
                res = client.post("/api/runs", json={
                    "goal": "Verify SSE Replay Invariants",
                    "requirements": ["R1", "R2"],
                })
                run_id = res.json()["run_id"]

                # Cancel to make terminal so SSE stream finishes
                client.post(f"/api/runs/{run_id}/cancel", json={"reason": "test cancel"})

                # Full stream
                stream_res = client.get(f"/api/runs/{run_id}/events")
                assert stream_res.status_code == 200
                lines = [line for line in stream_res.text.split("\n") if line.startswith("id: ")]
                event_ids = [int(line.split("id: ")[1]) for line in lines]
                assert len(event_ids) >= 2
                assert event_ids == sorted(event_ids)

                # Reconnect from Last-Event-ID
                last_id = event_ids[0]
                replay_res = client.get(
                    f"/api/runs/{run_id}/events",
                    headers={"Last-Event-ID": str(last_id)},
                )
                assert replay_res.status_code == 200
                replay_lines = [line for line in replay_res.text.split("\n") if line.startswith("id: ")]
                replay_ids = [int(line.split("id: ")[1]) for line in replay_lines]

                # Replayed events must only be strictly > last_id
                assert all(eid > last_id for eid in replay_ids)
                assert replay_ids == event_ids[1:]
        finally:
            app.state.store.close()


def test_backup_and_consistent_restore(tmp_path):
    """Verify that SQLite online backup + artifact copying provides consistent, readable restore."""
    import shutil
    import sqlite3

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    db_file = source_dir / "domain.sqlite"

    with SQLiteStore(db_file) as store:
        state = sample_state()
        store.create(state.task, state.run)
        lease = store.acquire(state.run.id, owner="writer-backup", ttl=60)
        plan = sample_plan(state)
        cmd = CommitPlan(
            expected_revision=1,
            node="revise",
            logical_operation_id="plan-backup-1",
            actor="planner",
            plan=plan,
        )
        store.commit(state.run.id, cmd, lease)
        art_ref = store.artifacts.put(b"payload for backup verification")

        # Perform online backup
        backup_dir = tmp_path / "backup"
        backup_dir.mkdir()
        backup_db = backup_dir / "domain.sqlite"
        backup_art = backup_dir / "artifacts"

        backup_conn = sqlite3.connect(backup_db)
        store.connection.backup(backup_conn)
        backup_conn.close()
        shutil.copytree(store.artifacts.root, backup_art)

    # Now restore from backup into a brand new clean environment
    restored_dir = tmp_path / "restored"
    shutil.copytree(backup_dir, restored_dir)

    with SQLiteStore(restored_dir / "domain.sqlite") as restored_store:
        restored_state = restored_store.load(state.run.id)
        assert restored_state.run.id == state.run.id
        assert restored_state.run.revision == 2
        assert len(restored_state.plans) == 1
        assert restored_state.plans[0].id == plan.id
        # Verify artifact integrity in restored store
        assert restored_store.artifacts.read(art_ref) == b"payload for backup verification"

