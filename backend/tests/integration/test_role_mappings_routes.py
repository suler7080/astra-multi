"""Integration tests for Role Mappings REST endpoints (Task 3)."""

import tempfile
from pathlib import Path
from fastapi.testclient import TestClient

from astra_multi.api.app import create_app


def test_get_roles_unconfigured():
    """Verify GET /api/settings/roles returns 200 and empty mappings when unconfigured."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        art_path = Path(tmpdir) / "artifacts"
        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)

        with TestClient(app) as client:
            res = client.get("/api/settings/roles")
            assert res.status_code == 200
            data = res.json()
            assert data["mappings"] == {}
            assert data["active_provider"] is not None
            assert data["planner"] is None
            assert data["reviewer"] is None
            assert data["synthesizer"] is None


def test_put_roles_valid_and_get():
    """Verify PUT valid role mappings and retrieving them via GET matches 100%."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        art_path = Path(tmpdir) / "artifacts"
        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)

        with TestClient(app) as client:
            # PUT valid assignment using seeded 'xkiro' provider
            payload = {
                "planner": {"provider": "xkiro", "model": "qwen/qwen3.7-flash:free"},
                "reviewer": {"provider": "xkiro", "model": None},
            }
            put_res = client.put("/api/settings/roles", json=payload)
            assert put_res.status_code == 200
            data = put_res.json()

            assert data["mappings"]["planner"]["provider"] == "xkiro"
            assert data["mappings"]["planner"]["model"] == "qwen/qwen3.7-flash:free"
            assert data["mappings"]["reviewer"]["provider"] == "xkiro"
            assert data["mappings"]["reviewer"]["model"] is None
            assert "synthesizer" not in data["mappings"]

            # Verify GET returns identical data
            get_res = client.get("/api/settings/roles")
            assert get_res.status_code == 200
            get_data = get_res.json()
            assert get_data["mappings"] == data["mappings"]
            assert get_data["planner"] == data["planner"]
            assert get_data["reviewer"] == data["reviewer"]
            assert get_data["synthesizer"] is None


def test_put_roles_model_whitespace_normalized():
    """Verify empty or whitespace-only model is normalized to None."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        art_path = Path(tmpdir) / "artifacts"
        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)

        with TestClient(app) as client:
            payload = {
                "planner": {"provider": "xkiro", "model": "   "},
            }
            res = client.put("/api/settings/roles", json=payload)
            assert res.status_code == 200
            data = res.json()
            assert data["mappings"]["planner"]["model"] is None


def test_put_roles_nonexistent_provider_returns_400():
    """Verify assigning a nonexistent provider returns 400 with descriptive error."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        art_path = Path(tmpdir) / "artifacts"
        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)

        with TestClient(app) as client:
            payload = {
                "reviewer": {"provider": "ghost_provider_404", "model": "any"},
            }
            res = client.put("/api/settings/roles", json=payload)
            assert res.status_code == 400
            err_msg = res.json()["detail"]
            assert "ghost_provider_404" in err_msg
            assert "reviewer" in err_msg


def test_put_roles_disabled_or_no_key_provider_returns_400():
    """Verify assigning a provider that has no API key and is inactive returns 400."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        art_path = Path(tmpdir) / "artifacts"
        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)

        # Save a provider with no key and is_active=False
        app.state.store.settings.save_provider(
            name="disabled-ollama",
            kind="openai-compatible",
            model="llama3",
            base_url="http://localhost:11434",
            api_key_enc=None,
            is_active=False,
        )

        with TestClient(app) as client:
            payload = {
                "synthesizer": {"provider": "disabled-ollama", "model": None},
            }
            res = client.put("/api/settings/roles", json=payload)
            assert res.status_code == 400
            err_msg = res.json()["detail"]
            assert "disabled-ollama" in err_msg
            assert "synthesizer" in err_msg


def test_put_roles_extra_key_rejected():
    """Verify payload with unrecognized keys is rejected with 422."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        art_path = Path(tmpdir) / "artifacts"
        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)

        with TestClient(app) as client:
            # Top-level unknown role key
            payload_unknown_role = {
                "planner": {"provider": "xkiro"},
                "auditor": {"provider": "xkiro"},
            }
            res1 = client.put("/api/settings/roles", json=payload_unknown_role)
            assert res1.status_code == 422

            # Nested unknown item property
            payload_unknown_field = {
                "planner": {"provider": "xkiro", "extra_field": "disallowed"},
            }
            res2 = client.put("/api/settings/roles", json=payload_unknown_field)
            assert res2.status_code == 422


def test_put_roles_empty_payload_clears_all():
    """Verify empty payload clears all existing role mappings."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        art_path = Path(tmpdir) / "artifacts"
        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)

        with TestClient(app) as client:
            # 1. First set some mappings
            client.put(
                "/api/settings/roles",
                json={"planner": {"provider": "xkiro"}},
            )
            assert client.get("/api/settings/roles").json()["mappings"] != {}

            # 2. Empty PUT
            res = client.put("/api/settings/roles", json={})
            assert res.status_code == 200
            data = res.json()
            assert data["mappings"] == {}

            # 3. GET confirms mappings are cleared
            get_res = client.get("/api/settings/roles")
            assert get_res.json()["mappings"] == {}


def test_roles_endpoints_admin_protection():
    """Verify endpoints require Admin when admin password is configured."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        art_path = Path(tmpdir) / "artifacts"
        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)

        with TestClient(app) as client:
            # Setup admin password
            setup_res = client.post("/api/auth/setup", json={"password": "admin-password-xyz"})
            assert setup_res.status_code == 200
            token = setup_res.json()["token"]

            # GET without token fails (401)
            get_unauth = client.get("/api/settings/roles")
            assert get_unauth.status_code == 401

            # PUT without token fails (401)
            put_unauth = client.put("/api/settings/roles", json={})
            assert put_unauth.status_code == 401

            # Access with valid token succeeds (200)
            headers = {"Authorization": f"Bearer {token}"}
            get_auth = client.get("/api/settings/roles", headers=headers)
            assert get_auth.status_code == 200

            put_auth = client.put("/api/settings/roles", json={}, headers=headers)
            assert put_auth.status_code == 200


def test_roles_response_contains_no_secrets():
    """Verify response payload contains no API keys or encrypted credentials."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        art_path = Path(tmpdir) / "artifacts"
        app = create_app(db_path=db_path, artifacts_dir=art_path, auto_start_worker=False)

        with TestClient(app) as client:
            client.put(
                "/api/settings/roles",
                json={"planner": {"provider": "xkiro", "model": "m1"}},
            )
            raw_text = client.get("/api/settings/roles").text

            assert "api_key" not in raw_text
            assert "api_key_enc" not in raw_text
            assert "secret" not in raw_text
            assert "password" not in raw_text
