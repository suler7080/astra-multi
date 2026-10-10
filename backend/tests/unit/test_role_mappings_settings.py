import sqlite3
from astra_multi.persistence.settings_store import SettingsStore


def setup_in_memory_settings_store() -> SettingsStore:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    conn.commit()
    return SettingsStore(lambda: conn)


def test_get_role_mappings_returns_empty_dict_when_unset():
    store = setup_in_memory_settings_store()
    # Chưa lưu gì
    result = store.get_role_mappings()
    assert result == {}
    assert isinstance(result, dict)


def test_save_and_get_role_mappings_round_trip():
    store = setup_in_memory_settings_store()
    mappings = {
        "planner": {"provider": "xkiro", "model": "qwen/qwen3.7-max:free"},
        "reviewer": {"provider": "google", "model": "gemini-2.0-flash"},
        "synthesizer": {"provider": "openai", "model": "gpt-4o-mini"},
    }
    store.save_role_mappings(mappings)
    loaded = store.get_role_mappings()
    assert loaded == mappings
    assert loaded["planner"]["provider"] == "xkiro"
    assert loaded["planner"]["model"] == "qwen/qwen3.7-max:free"
    assert loaded["reviewer"]["provider"] == "google"
    assert loaded["synthesizer"]["provider"] == "openai"


def test_get_role_mappings_handles_malformed_json_gracefully():
    store = setup_in_memory_settings_store()
    # Ghi chuỗi không phải JSON hợp lệ vào DB
    store.set_setting("role_mappings", "not-a-valid-json{{{")
    result = store.get_role_mappings()
    assert result == {}

    # Ghi JSON nhưng không phải dict (ví dụ list hoặc số)
    store.set_setting("role_mappings", "12345")
    assert store.get_role_mappings() == {}

    store.set_setting("role_mappings", "[\"planner\", \"reviewer\"]")
    assert store.get_role_mappings() == {}


def test_save_role_mappings_overwrites_existing():
    store = setup_in_memory_settings_store()
    store.save_role_mappings({"planner": {"provider": "provider_a", "model": None}})
    assert store.get_role_mappings() == {"planner": {"provider": "provider_a", "model": None}}

    # Ghi đè cấu hình mới
    updated = {
        "planner": {"provider": "provider_b", "model": "model-x"},
        "reviewer": {"provider": "provider_c", "model": "model-y"},
    }
    store.save_role_mappings(updated)
    assert store.get_role_mappings() == updated
