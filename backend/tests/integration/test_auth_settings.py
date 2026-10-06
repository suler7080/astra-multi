"""Integration tests for Authentication and Settings endpoints."""

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from astra_multi.api.app import create_app


def test_auth_setup_login_and_protection():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        art_path = Path(tmpdir) / "artifacts"
        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)

        with TestClient(app) as client:
            # 1. Initial status: setup required
            status_res = client.get("/api/auth/status")
            assert status_res.status_code == 200
            assert status_res.json() == {"setup_required": True, "authenticated": False}

            # 2. Setup initial admin password
            setup_res = client.post("/api/auth/setup", json={"password": "admin-secure-123"})
            assert setup_res.status_code == 200
            token = setup_res.json()["token"]
            assert token

            # Cannot setup again once configured
            fail_setup = client.post("/api/auth/setup", json={"password": "another-pass"})
            assert fail_setup.status_code == 400

            # 3. Status with token
            auth_status = client.get("/api/auth/status", headers={"Authorization": f"Bearer {token}"})
            assert auth_status.status_code == 200
            assert auth_status.json() == {"setup_required": False, "authenticated": True}

            # 4. Login with wrong password
            wrong_login = client.post("/api/auth/login", json={"password": "wrong-password"})
            assert wrong_login.status_code == 401

            # 5. Login with correct password
            good_login = client.post("/api/auth/login", json={"password": "admin-secure-123"})
            assert good_login.status_code == 200
            login_token = good_login.json()["token"]
            assert login_token

            # 6. Access /api/runs without token should fail now that password is set
            unauth_runs = client.get("/api/runs")
            assert unauth_runs.status_code == 401

            # 7. Access /api/runs with token succeeds
            auth_runs = client.get("/api/runs", headers={"Authorization": f"Bearer {login_token}"})
            assert auth_runs.status_code == 200

            # 8. Change password
            change_res = client.post(
                "/api/auth/change-password",
                json={"current_password": "admin-secure-123", "new_password": "new-admin-456"},
                headers={"Authorization": f"Bearer {login_token}"},
            )
            assert change_res.status_code == 200

            # Old password fails
            old_login = client.post("/api/auth/login", json={"password": "admin-secure-123"})
            assert old_login.status_code == 401

            # New password works
            new_login = client.post("/api/auth/login", json={"password": "new-admin-456"})
            assert new_login.status_code == 200


def test_provider_settings_crud_and_activation():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        art_path = Path(tmpdir) / "artifacts"
        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)

        with TestClient(app) as client:
            # List providers (seeds xkiro, openai, google)
            list_res = client.get("/api/settings/providers")
            assert list_res.status_code == 200
            providers = list_res.json()
            assert len(providers) >= 3
            names = [p["name"] for p in providers]
            assert "xkiro" in names

            # Active provider is xkiro
            active_p = next(p for p in providers if p["name"] == "xkiro")
            assert active_p["is_active"] is True
            assert active_p["model"] == "qwen/qwen3.7-flash:free"

            # Create a new custom provider
            create_res = client.post(
                "/api/settings/providers",
                json={
                    "name": "custom-ollama",
                    "kind": "openai-compatible",
                    "base_url": "http://127.0.0.1:11434/v1",
                    "model": "llama3.2:latest",
                    "api_key": "ollama-dummy-key",
                    "is_active": False,
                },
            )
            assert create_res.status_code == 200
            data = create_res.json()
            assert data["name"] == "custom-ollama"
            assert data["has_api_key"] is True
            assert data["is_active"] is False

            # Activate the custom provider
            act_res = client.post("/api/settings/providers/custom-ollama/activate")
            assert act_res.status_code == 200
            assert act_res.json()["active_provider"] == "custom-ollama"

            # Verify custom provider is now active and xkiro is not
            updated_list = client.get("/api/settings/providers").json()
            ollama_p = next(p for p in updated_list if p["name"] == "custom-ollama")
            xkiro_p = next(p for p in updated_list if p["name"] == "xkiro")
            assert ollama_p["is_active"] is True
            assert xkiro_p["is_active"] is False

            # Cannot delete active provider
            del_fail = client.delete("/api/settings/providers/custom-ollama")
            assert del_fail.status_code == 400

            # Re-activate xkiro and delete custom-ollama
            client.post("/api/settings/providers/xkiro/activate")
            del_ok = client.delete("/api/settings/providers/custom-ollama")
            assert del_ok.status_code == 200
