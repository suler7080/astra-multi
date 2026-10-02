import os
import subprocess

import pytest

from astra_multi.context.snapshots import (
    SelectionPolicy,
    SnapshotError,
    SnapshotStore,
)
from astra_multi.persistence.artifacts import FileArtifactStore


@pytest.mark.skipif(os.name != "posix", reason="NOT_RUN: POSIX FIFO capture race")
def test_regular_file_replaced_by_fifo_does_not_block_capture(tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    path = root / "app.py"
    path.write_text("original")
    store = SnapshotStore(FileArtifactStore(tmp_path / "artifacts"))
    read = store._read

    def replace_before_open(root, path, maximum):
        path.unlink()
        os.mkfifo(path)
        return read(root, path, maximum)

    monkeypatch.setattr(store, "_read", replace_before_open)
    with pytest.raises(SnapshotError, match="non-regular"):
        store.capture(root, attempts=1)


@pytest.fixture
def snapshot_store(tmp_path):
    return SnapshotStore(FileArtifactStore(tmp_path / "artifacts"))


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, check=True,
    ).stdout


def test_git_clean_dirty_untracked_selection_and_frozen_content(tmp_path, snapshot_store):
    root = tmp_path / "repo có dấu"
    root.mkdir()
    git(root, "init")
    (root / "file space.txt").write_text("original")
    (root / ".gitignore").write_text("ignored.txt\n")
    git(root, "add", "file space.txt", ".gitignore")
    git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test",
        "commit", "-m", "fixture")
    clean = snapshot_store.capture(root)
    assert clean.snapshot.commit_if_any
    assert not clean.snapshot.dirty
    (root / "file space.txt").write_text("dirty")
    (root / "untracked.txt").write_text("selected")
    (root / "ignored.txt").write_text("excluded")
    (root / ".env").write_text("synthetic secret")
    dirty = snapshot_store.capture(root)
    assert dirty.snapshot.dirty
    assert snapshot_store.read(dirty, "file space.txt") == b"dirty"
    assert snapshot_store.read(dirty, "untracked.txt") == b"selected"
    manifest = snapshot_store.manifest(dirty)
    assert manifest.excluded["ignored.txt"] == "git-selection"
    assert manifest.excluded[".env"] == ".env*"
    tracked = snapshot_store.capture(root, SelectionPolicy(include_untracked=False))
    assert "untracked.txt" not in tracked.snapshot.file_hashes
    (root / "file space.txt").write_text("later")
    assert snapshot_store.read(clean, "file space.txt") == b"original"
    assert snapshot_store.read(dirty, "file space.txt") == b"dirty"


def test_non_git_manifest_stability_and_materialization(tmp_path, snapshot_store):
    root = tmp_path / "non git"
    root.mkdir()
    (root / "đường dẫn.py").write_text("print('hello')\n", encoding="utf-8")
    one = snapshot_store.capture(root)
    two = snapshot_store.capture(root)
    assert one.snapshot.commit_if_any is None
    assert one.manifest == two.manifest
    destination = tmp_path / "copy"
    snapshot_store.materialize(one, destination)
    assert (destination / "đường dẫn.py").read_bytes() == (root / "đường dẫn.py").read_bytes()
    with pytest.raises(SnapshotError):
        snapshot_store.materialize(one, destination)


def test_capture_detects_changes_and_bounded_retry(tmp_path, snapshot_store):
    root = tmp_path / "changing"
    root.mkdir()
    target = root / "app.py"
    target.write_text("one")
    calls = []

    def mutate():
        calls.append(1)
        target.write_text(str(len(calls)))

    with pytest.raises(SnapshotError, match="not consistent"):
        snapshot_store.capture(root, attempts=2, between_scans=mutate)
    assert len(calls) == 2

    def mutate_once():
        if target.read_text() != "stable":
            target.write_text("stable")

    ref = snapshot_store.capture(root, between_scans=mutate_once)
    assert snapshot_store.read(ref, "app.py") == b"stable"


@pytest.mark.parametrize("path", ["../escape", "/etc/passwd", "C:/escape", "a/../b", "a\\b"])
def test_path_escape_rejected(tmp_path, snapshot_store, path):
    root = tmp_path / "source"
    root.mkdir()
    ref = snapshot_store.capture(root)
    with pytest.raises(SnapshotError):
        snapshot_store.read(ref, path)


def test_links_are_excluded_and_artifact_tampering_fails(tmp_path, snapshot_store):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "file").write_bytes(b"content")
    secret = tmp_path / "outside"
    secret.write_bytes(b"outside")
    try:
        (root / "escape").symlink_to(secret)
        (root / "internal").symlink_to(root / "file")
    except OSError:
        pytest.skip("NOT_RUN: symlink creation unavailable")
    ref = snapshot_store.capture(root)
    assert snapshot_store.manifest(ref).excluded["escape"] == "link/reparse-point"
    with pytest.raises(SnapshotError):
        snapshot_store.read(ref, "internal")
    content_ref = snapshot_store.manifest(ref).files["file"].artifact
    artifact = tmp_path / "artifacts" / content_ref.content_hash
    artifact.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash or size"):
        snapshot_store.read(ref, "file")


def test_capture_quotas_and_case_collision(tmp_path, snapshot_store):
    root = tmp_path / "source"
    root.mkdir()
    (root / "big").write_bytes(b"1234")
    with pytest.raises(SnapshotError, match="quota"):
        snapshot_store.capture(root, SelectionPolicy(max_file_bytes=3))
    (root / "BIG").write_bytes(b"other")
    if len(list(root.iterdir())) < 2:
        pytest.skip("case-sensitive filesystem required")
    with pytest.raises(SnapshotError, match="collision"):
        snapshot_store.capture(root)
