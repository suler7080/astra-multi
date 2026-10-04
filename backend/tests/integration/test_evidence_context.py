import pytest

from astra_multi.context.bundle import ContextBuilder, ContextLimits, ContextOverflow
from astra_multi.context.evidence import EvidenceLedger
from astra_multi.context.snapshots import SnapshotStore
from astra_multi.domain.fixtures import sample_state
from astra_multi.domain.models import RunPhase, ValidationStatus
from astra_multi.persistence.sqlite import SQLiteStore
from astra_multi.tools.broker import ToolBroker
from astra_multi.tools.contracts import ToolRequest


def setup_run(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    # Use write_bytes to avoid line ending conversion
    (root / "app.py").write_bytes(b"def health():\n    return 'ok'\n" * 100)
    store = SQLiteStore(tmp_path / "state.sqlite")
    snapshots = SnapshotStore(store.artifacts)
    ref = snapshots.capture(root)
    state = sample_state()
    run = state.run.model_copy(update={"mode": "repo", "snapshot_id": ref.snapshot.id})
    store.create(state.task, run, ref.snapshot)
    lease = store.acquire(run.id, "test")
    broker = ToolBroker(run, snapshots, ref)
    result = broker.execute(ToolRequest(
        run_id=run.id, snapshot_id=run.snapshot_id, call_id="READ-001",
        action="read", path="app.py",
    ))
    return store, EvidenceLedger(store, store.artifacts, lease), result, root, snapshots


def test_durable_evidence_claims_and_read_never_means_test_pass(tmp_path):
    store, ledger, result, _, _ = setup_run(tmp_path)
    try:
        evidence = ledger.record(result)
        assert evidence.status == ValidationStatus.NOT_RUN
        ledger.claim("app.py defines health", [evidence.id], "CLAIM-001")
        revision = store.load(ledger.lease.run_id).run.revision
        assert ledger.record(result) == evidence
        assert store.load(ledger.lease.run_id).run.revision == revision
        with pytest.raises(ValueError):
            ledger.claim("unsupported", [], "CLAIM-002")
        with pytest.raises(ValueError):
            ledger.record(result.model_copy(
                update={"request": result.request.model_copy(update={"run_id": "OTHER"})},
            ))
        with pytest.raises(ValueError, match="source"):
            ledger.record(result.model_copy(update={
                "sources": (result.sources[0].model_copy(update={"snapshot_id": "OLD"}),),
            }))
        store.close()
        with SQLiteStore(tmp_path / "state.sqlite") as reopened:
            persisted = reopened.load(ledger.lease.run_id)
            assert persisted.claims[0].evidence_ids == [evidence.id]
            assert persisted.tool_calls[0].arguments_redacted["sources"]
            assert not persisted.validations
            assert reopened.artifacts.read(persisted.evidence[0].artifact) == b"def health():\n    return 'ok'\n" * 100
    finally:
        store.close()


class CharacterTokenizer:
    def count(self, text):
        return len(text)


def test_independent_context_limits_and_essential_provenance(tmp_path):
    store, ledger, result, _, _ = setup_run(tmp_path)
    try:
        evidence = ledger.record(result)
        state = store.load(ledger.lease.run_id)
        builder = ContextBuilder(store.artifacts, CharacterTokenizer())
        first = builder.build_context(state, "planner", RunPhase.INDEPENDENT_ANALYSIS,
                                      [evidence.id], ContextLimits(max_tokens=1500))
        second = builder.build_context(state, "reviewer", RunPhase.INDEPENDENT_ANALYSIS,
                                       [evidence.id], ContextLimits(max_tokens=1500))
        assert first.content == second.content
        assert first.token_count <= 1500
        assert evidence.id in first.source_ids
        assert evidence.id in first.content
        assert evidence.content_hash in first.content
        assert first.truncated_ids == (evidence.id,)
        with pytest.raises(ContextOverflow):
            builder.build_context(state, "planner", RunPhase.INDEPENDENT_ANALYSIS,
                                  [evidence.id], ContextLimits(max_tokens=1))
        with pytest.raises(ValueError):
            builder.build_context(state, "planner", RunPhase.REVIEW,
                                  ["missing"], ContextLimits())
    finally:
        store.close()


def test_old_snapshot_evidence_rejected_for_new_code(tmp_path):
    store, ledger, result, root, snapshots = setup_run(tmp_path)
    try:
        ledger.record(result)
        old = store.load(ledger.lease.run_id)
        (root / "app.py").write_text("new implementation")
        ref = snapshots.capture(root)
        assert ref.snapshot.id != old.snapshot.id
        changed = old.model_copy(update={
            "snapshot": ref.snapshot,
            "run": old.run.model_copy(update={"snapshot_id": ref.snapshot.id}),
        })
        with pytest.raises(ValueError):
            ContextBuilder(store.artifacts).build_context(
                changed, "planner", RunPhase.INDEPENDENT_ANALYSIS, [], ContextLimits(),
            )
    finally:
        store.close()
