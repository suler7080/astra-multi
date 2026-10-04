import json

import pytest

from astra_multi.context.snapshots import digest
from astra_multi.p2_demo import investigate
from astra_multi.persistence.sqlite import SQLiteStore
from astra_multi.sandbox.runner import SandboxProfile


def source_hash(root):
    return {str(p.relative_to(root)): digest(p.read_bytes()) for p in root.rglob("*") if p.is_file()}


def test_demo_traces_claims_and_not_run_without_changing_source(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "app.py").write_text("print('fixture')")
    before = source_hash(root)
    encoded = investigate(
        root, tmp_path / "workspace", ("python", "app.py"),
        SandboxProfile(target_os="windows"),
    )
    report = json.loads(encoded)
    assert report["job"]["status"] == "unavailable"
    assert report["validation"]["status"] == "NOT_RUN"
    assert report["snapshot"]["snapshot"]["file_hashes"]
    with SQLiteStore(tmp_path / "workspace" / "domain.sqlite") as store:
        state = store.load(report["run_id"])
        assert state.claims[0].evidence_ids[0] == report["evidence_index"][0]["id"]
        assert all(e.snapshot_id == state.run.snapshot_id for e in state.evidence)
        assert all(store.artifacts.read(e.artifact) for e in state.evidence)
    assert source_hash(root) == before
    with pytest.raises(ValueError, match="outside"):
        investigate(root, root / "output", ("python", "app.py"))
