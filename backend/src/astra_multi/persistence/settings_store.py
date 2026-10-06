from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SettingsStore:
    """Manages persistent application settings and encrypted provider configurations in SQLite."""

    def __init__(
        self,
        connection_provider: Callable[[], sqlite3.Connection],
    ) -> None:
        self._get_connection = connection_provider

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        conn = self._get_connection()
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()

    def delete_setting(self, key: str) -> None:
        conn = self._get_connection()
        conn.execute("DELETE FROM app_settings WHERE key = ?", (key,))
        conn.commit()

    def get_all_settings(self) -> dict[str, str]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM app_settings")
        return {row[0]: row[1] for row in cursor.fetchall()}

    def list_providers(self) -> list[dict[str, Any]]:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name, kind, base_url, model, api_key_enc, is_active, created_at, updated_at "
            "FROM provider_configs ORDER BY created_at ASC"
        )
        results = []
        for row in cursor.fetchall():
            results.append({
                "name": row[0],
                "kind": row[1],
                "base_url": row[2],
                "model": row[3],
                "api_key_enc": row[4],
                "is_active": bool(row[5]),
                "created_at": row[6],
                "updated_at": row[7],
            })
        return results

    def get_provider(self, name: str) -> dict[str, Any] | None:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name, kind, base_url, model, api_key_enc, is_active, created_at, updated_at "
            "FROM provider_configs WHERE name = ?",
            (name,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "name": row[0],
            "kind": row[1],
            "base_url": row[2],
            "model": row[3],
            "api_key_enc": row[4],
            "is_active": bool(row[5]),
            "created_at": row[6],
            "updated_at": row[7],
        }

    def save_provider(
        self,
        name: str,
        kind: str,
        model: str,
        base_url: str | None = None,
        api_key_enc: str | None = None,
        is_active: bool = False,
    ) -> None:
        conn = self._get_connection()
        now = utc_now_iso()
        existing = self.get_provider(name)
        if existing:
            # Preserve existing api_key_enc if None was supplied
            enc_to_use = api_key_enc if api_key_enc is not None else existing.get("api_key_enc")
            conn.execute(
                "UPDATE provider_configs SET kind = ?, base_url = ?, model = ?, "
                "api_key_enc = ?, is_active = ?, updated_at = ? WHERE name = ?",
                (kind, base_url, model, enc_to_use, int(is_active), now, name),
            )
        else:
            conn.execute(
                "INSERT INTO provider_configs "
                "(name, kind, base_url, model, api_key_enc, is_active, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (name, kind, base_url, model, api_key_enc, int(is_active), now, now),
            )
        if is_active:
            # Unset active on all other providers
            conn.execute(
                "UPDATE provider_configs SET is_active = 0 WHERE name != ?",
                (name,),
            )
        conn.commit()

    def set_active_provider(self, name: str) -> None:
        conn = self._get_connection()
        conn.execute("UPDATE provider_configs SET is_active = 0")
        conn.execute("UPDATE provider_configs SET is_active = 1 WHERE name = ?", (name,))
        conn.commit()

    def get_active_provider(self) -> dict[str, Any] | None:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name, kind, base_url, model, api_key_enc, is_active, created_at, updated_at "
            "FROM provider_configs WHERE is_active = 1 LIMIT 1"
        )
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "name": row[0],
            "kind": row[1],
            "base_url": row[2],
            "model": row[3],
            "api_key_enc": row[4],
            "is_active": True,
            "created_at": row[6],
            "updated_at": row[7],
        }

    def delete_provider(self, name: str) -> None:
        conn = self._get_connection()
        conn.execute("DELETE FROM provider_configs WHERE name = ?", (name,))
        conn.commit()
