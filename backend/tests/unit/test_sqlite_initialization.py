"""Initialization errors must release a connection even before migrations."""

import sqlite3
from pathlib import Path

import pytest

from astra_multi.persistence import SQLiteStore


@pytest.mark.parametrize(
    "failure",
    ["PRAGMA foreign_keys=ON", "PRAGMA journal_mode=WAL", "PRAGMA synchronous=FULL"],
)
def test_initialization_failure_closes_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    class FailingConnection(sqlite3.Connection):
        def execute(
            self, sql: str, parameters: tuple[object, ...] = ()
        ) -> sqlite3.Cursor:
            if sql == failure:
                raise sqlite3.OperationalError("injected initialization failure")
            return super().execute(sql, parameters)

    database = tmp_path / "domain.sqlite"
    connection = sqlite3.connect(
        database, factory=FailingConnection, isolation_level=None
    )

    def connect(
        path: Path, *, isolation_level: None, timeout: int
    ) -> FailingConnection:
        return connection

    monkeypatch.setattr(sqlite3, "connect", connect)
    try:
        with pytest.raises(sqlite3.OperationalError, match="injected initialization"):
            SQLiteStore(database)
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
    finally:
        connection.close()
