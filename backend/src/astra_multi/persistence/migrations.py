import sqlite3

MIGRATIONS: tuple[tuple[str, ...], ...] = (
    (
        "CREATE TABLE runs (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, state_json TEXT NOT NULL)",
        "CREATE TABLE events (run_id TEXT NOT NULL REFERENCES runs(id), sequence INTEGER NOT NULL, event_json TEXT NOT NULL, PRIMARY KEY (run_id, sequence))",
        "CREATE TABLE operations (run_id TEXT NOT NULL REFERENCES runs(id), node TEXT NOT NULL, logical_operation_id TEXT NOT NULL, operation_json TEXT NOT NULL, PRIMARY KEY (run_id, node, logical_operation_id))",
        "CREATE TABLE leases (run_id TEXT PRIMARY KEY REFERENCES runs(id), owner TEXT NOT NULL, token TEXT NOT NULL, epoch INTEGER NOT NULL, expires_at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS provider_configs (name TEXT PRIMARY KEY, kind TEXT NOT NULL, base_url TEXT, model TEXT NOT NULL, api_key_enc TEXT, is_active INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
    ),
)


def migrate(connection: sqlite3.Connection) -> None:
    connection.execute("BEGIN IMMEDIATE")
    try:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version > len(MIGRATIONS):
            raise ValueError("database schema is newer than this application")
        for index in range(version, len(MIGRATIONS)):
            for statement in MIGRATIONS[index]:
                connection.execute(statement)
            connection.execute(f"PRAGMA user_version = {index + 1}")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS provider_configs (name TEXT PRIMARY KEY, kind TEXT NOT NULL, base_url TEXT, model TEXT NOT NULL, api_key_enc TEXT, is_active INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
