from pathlib import Path

import pytest

from astra_multi.execution.file_scope import FileScopeBroker, FileScopeDenied


def test_file_scope_allows_owned_file_and_rejects_escape(tmp_path: Path):
    broker = FileScopeBroker(tmp_path, ["src/api.py"])
    broker.write("src/api.py", "value = 1")

    assert broker.read("src/api.py") == "value = 1"
    with pytest.raises(FileScopeDenied, match="outside worker scope"):
        broker.write("src/other.py", "blocked")
    with pytest.raises(FileScopeDenied, match="outside repository"):
        broker.read("../outside.py")


def test_file_scope_detects_out_of_scope_changes(tmp_path: Path):
    owned = tmp_path / "src" / "api.py"
    owned.parent.mkdir()
    owned.write_text("before", encoding="utf-8")
    broker = FileScopeBroker(tmp_path, ["src/api.py"])
    before = broker.snapshot()

    (tmp_path / "README.md").write_text("unexpected", encoding="utf-8")

    with pytest.raises(FileScopeDenied, match="outside declared scope"):
        broker.verify_snapshot(before)


def test_file_scope_allows_declared_file_change(tmp_path: Path):
    broker = FileScopeBroker(tmp_path, ["src/api.py"])
    before = broker.snapshot()
    broker.write("src/api.py", "created")

    broker.verify_snapshot(before)
