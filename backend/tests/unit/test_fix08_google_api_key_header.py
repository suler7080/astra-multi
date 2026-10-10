"""Tests for FIX-08: Google Gemini API Key passed via x-goog-api-key header instead of query param.

Verifies:
1. Google provider connection probe does NOT include the api key in the URL query parameters.
2. Google provider connection probe attaches the api key in the 'x-goog-api-key' HTTP header.
3. Successful probe returns success=True.
4. Error responses (e.g. 403 Forbidden) are cleanly captured.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from astra_multi.api.app import create_app


def test_google_provider_test_connection_uses_header_not_query_param():
    """Google Gemini probe passes api_key via 'x-goog-api-key' header and never in URL query string."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_fix08.db"
        art_path = Path(tmpdir) / "artifacts"
        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)
        client = TestClient(app)

        try:
            mock_resp = httpx.Response(
                status_code=200,
                json={"candidates": [{"content": {"parts": [{"text": "pong"}]}}]},
            )

            with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
                mock_post.return_value = mock_resp

                secret_key = "AIzaSyD-secret-test-key-9999"
                payload = {
                    "kind": "google",
                    "model": "gemini-1.5-flash",
                    "api_key": secret_key,
                    "base_url": "https://generativelanguage.googleapis.com/v1beta",
                }

                resp = client.post("/api/settings/providers/test", json=payload)
                assert resp.status_code == 200
                data = resp.json()
                assert data["success"] is True

                # Verify mock_post call arguments
                assert mock_post.called
                called_args, called_kwargs = mock_post.call_args
                called_url = called_args[0]
                called_headers = called_kwargs.get("headers", {})

                # 1. URL must NOT contain the secret key or query param
                assert "key=" not in called_url
                assert secret_key not in called_url
                assert (
                    called_url
                    == "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
                )

                # 2. Header must contain x-goog-api-key with the secret
                assert "x-goog-api-key" in called_headers
                assert called_headers["x-goog-api-key"] == secret_key
                assert called_headers["Content-Type"] == "application/json"
        finally:
            app.state.store.close()


def test_google_provider_test_connection_handles_http_error():
    """Google Gemini probe gracefully reports error on HTTP 400+ without exposing secrets."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_fix08_err.db"
        art_path = Path(tmpdir) / "artifacts"
        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)
        client = TestClient(app)

        try:
            mock_resp = httpx.Response(status_code=403, text='{"error": {"message": "API_KEY_INVALID"}}')

            with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
                mock_post.return_value = mock_resp

                payload = {
                    "kind": "google",
                    "model": "gemini-1.5-pro",
                    "api_key": "bad-key",
                }

                resp = client.post("/api/settings/providers/test", json=payload)
                assert resp.status_code == 200
                data = resp.json()
                assert data["success"] is False
                assert "HTTP 403" in data["error"]
        finally:
            app.state.store.close()
