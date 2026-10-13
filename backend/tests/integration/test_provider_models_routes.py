"""Integration tests for provider model discovery endpoints."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from astra_multi.api.app import create_app
from astra_multi.persistence.sqlite import SQLiteStore
from astra_multi.security.crypto import create_access_token, ensure_auth_secret_key, hash_password


@pytest.fixture
def test_setup(tmp_path: Path):
    db_path = tmp_path / "domain.sqlite"
    store = SQLiteStore(db_path)
    # Set up admin password
    secret = ensure_auth_secret_key(store.settings)
    h, s = hash_password("adminpass123")
    store.settings.set_setting("admin_password_hash", h)
    store.settings.set_setting("admin_password_salt", s)
    token = create_access_token(secret)
    headers = {"Authorization": f"Bearer {token}"}

    app = create_app(db_path=db_path, auto_start_worker=False)
    client = TestClient(app)
    return client, headers, store


def test_get_provider_models_not_found(test_setup):
    client, headers, _ = test_setup
    resp = client.get("/api/settings/providers/nonexistent/models", headers=headers)
    assert resp.status_code == 404


def test_get_provider_models_unauthorized(test_setup):
    client, _, _ = test_setup
    resp = client.get("/api/settings/providers/xkiro/models")
    assert resp.status_code in (401, 403)


def test_get_provider_models_success(test_setup):
    client, headers, store = test_setup

    # Save a provider
    save_resp = client.post(
        "/api/settings/providers",
        json={
            "name": "mock-xkiro",
            "kind": "openai-compatible",
            "base_url": "https://api.mock.com/v1",
            "model": "qwen3.7-flash",
            "api_key": "sk-mock-123",
            "is_active": True,
        },
        headers=headers,
    )
    assert save_resp.status_code == 200

    mock_resp_json = {
        "data": [
            {"id": "qwen/qwen3.7-max:free"},
            {"id": "qwen/qwen3.7-flash:free"},
            {"id": "deepseek/deepseek-v3"},
        ]
    }

    mock_httpx = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_resp_json
    mock_httpx.get.return_value = mock_resp

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__.return_value = mock_httpx
        mock_client_instance.__aexit__.return_value = None
        mock_client_cls.return_value = mock_client_instance

        resp = client.get("/api/settings/providers/mock-xkiro/models", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "mock-xkiro"
        assert data["count"] == 3
        # :free models should be sorted first
        assert data["models"] == [
            "qwen/qwen3.7-flash:free",
            "qwen/qwen3.7-max:free",
            "deepseek/deepseek-v3",
        ]


def test_discover_models_post(test_setup):
    client, headers, _ = test_setup

    mock_resp_json = {
        "models": [
            {
                "name": "models/gemini-2.0-flash",
                "supportedGenerationMethods": ["generateContent"],
            },
            {
                "name": "models/gemini-2.0-pro",
                "supportedGenerationMethods": ["generateContent"],
            },
        ]
    }

    mock_httpx = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_resp_json
    mock_httpx.get.return_value = mock_resp

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__.return_value = mock_httpx
        mock_client_instance.__aexit__.return_value = None
        mock_client_cls.return_value = mock_client_instance

        resp = client.post(
            "/api/settings/providers/models",
            json={
                "kind": "google",
                "api_key": "AIzaSyMockKey",
            },
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["models"] == ["gemini-2.0-flash", "gemini-2.0-pro"]
