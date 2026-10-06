"""Authentication and LLM Provider Settings routes for Astra Multi."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from astra_multi.persistence.sqlite import SQLiteStore
from astra_multi.provider_config import (
    ProviderManager,
    ProviderProfile,
    ProviderSettingsRepository,
)
from astra_multi.security.crypto import (
    create_access_token,
    decrypt_secret,
    encrypt_secret,
    ensure_auth_secret_key,
    ensure_master_encryption_key,
    hash_password,
    verify_access_token,
    verify_password,
)

logger = logging.getLogger(__name__)


# Schemas
class AuthStatusResponse(BaseModel):
    setup_required: bool
    authenticated: bool


class AuthPasswordRequest(BaseModel):
    password: str = Field(min_length=4)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=4)


class AuthTokenResponse(BaseModel):
    token: str
    role: str = "admin"


class ProviderItemResponse(BaseModel):
    name: str
    kind: str
    base_url: str | None = None
    model: str
    has_api_key: bool
    is_active: bool
    created_at: str
    updated_at: str


class SaveProviderRequest(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9_-]{1,64}$")
    kind: str = Field(pattern=r"^(openai|google|openai-compatible)$")
    base_url: str | None = None
    model: str = Field(min_length=1)
    api_key: str | None = None
    is_active: bool = False


class TestProviderRequest(BaseModel):
    name: str | None = None
    kind: str = Field(pattern=r"^(openai|google|openai-compatible)$")
    base_url: str | None = None
    model: str = Field(min_length=1)
    api_key: str | None = None


class TestProviderResponse(BaseModel):
    success: bool
    latency_ms: float | None = None
    error: str | None = None


def apply_active_provider_to_environment(store: SQLiteStore) -> None:
    """Synchronizes active provider and its decrypted API key into environment variables and providers.json."""
    active = store.settings.get_active_provider()
    if not active:
        return

    name = active["name"]
    kind = active["kind"]
    model = active["model"]
    base_url = active.get("base_url")
    api_key_enc = active.get("api_key_enc")

    master_key = ensure_master_encryption_key(store.settings)
    api_key = decrypt_secret(api_key_enc, master_key) if api_key_enc else None

    # 1. Update active provider name in environment
    os.environ["ASTRA_MULTI_PROVIDER"] = name

    # 2. Update specific key environment variable
    if api_key:
        if "xkiro" in name.lower():
            os.environ["XKIRO_API_KEY"] = api_key
        elif kind == "openai":
            os.environ["OPENAI_API_KEY"] = api_key
        elif kind == "google":
            os.environ["GOOGLE_API_KEY"] = api_key
        else:
            env_var = f"{name.upper().replace('-', '_')}_API_KEY"
            os.environ[env_var] = api_key

    # 3. Synchronize to ProviderSettingsRepository / providers.json
    try:
        from pydantic import HttpUrl

        repo = ProviderSettingsRepository()
        prof = ProviderProfile(
            name=name,
            kind=kind,  # type: ignore[arg-type]
            model=model,
            base_url=HttpUrl(base_url) if base_url else None,
            credential_source="environment",
            api_key_env="XKIRO_API_KEY" if "xkiro" in name.lower() else (
                "OPENAI_API_KEY" if kind == "openai" else (
                    "GOOGLE_API_KEY" if kind == "google" else f"{name.upper().replace('-', '_')}_API_KEY"
                )
            ),
        )
        mgr = ProviderManager(repo)
        mgr.configure(prof)
    except Exception as exc:
        logger.warning("Could not sync active provider to providers.json: %s", exc)


def seed_initial_providers_if_empty(store: SQLiteStore) -> None:
    """Seeds default providers (Xkiro, OpenAI, Google) if database is empty."""
    providers = store.settings.list_providers()
    if providers:
        return

    master_key = ensure_master_encryption_key(store.settings)
    xkiro_key = os.environ.get("XKIRO_API_KEY")
    xkiro_enc = encrypt_secret(xkiro_key, master_key) if xkiro_key else None

    # Default Xkiro
    store.settings.save_provider(
        name="xkiro",
        kind="openai-compatible",
        model="qwen/qwen3.7-flash:free",
        base_url="https://api.xkiro.com/v1",
        api_key_enc=xkiro_enc,
        is_active=True,
    )

    # Standard OpenAI preset
    openai_key = os.environ.get("OPENAI_API_KEY")
    openai_enc = encrypt_secret(openai_key, master_key) if openai_key else None
    store.settings.save_provider(
        name="openai",
        kind="openai",
        model="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        api_key_enc=openai_enc,
        is_active=False,
    )

    # Standard Google preset
    google_key = os.environ.get("GOOGLE_API_KEY")
    google_enc = encrypt_secret(google_key, master_key) if google_key else None
    store.settings.save_provider(
        name="google",
        kind="google",
        model="gemini-2.0-flash",
        api_key_enc=google_enc,
        is_active=False,
    )

    apply_active_provider_to_environment(store)


def create_auth_settings_router(store: SQLiteStore) -> APIRouter:
    """Creates FastAPI router for authentication and provider settings."""
    router = APIRouter(prefix="/api", tags=["auth_and_settings"])

    seed_initial_providers_if_empty(store)

    def require_admin(authorization: str | None = Header(default=None)) -> dict[str, Any] | None:
        admin_hash = store.settings.get_setting("admin_password_hash")
        if not admin_hash:
            # Setup mode: no password configured yet
            return None

        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )

        token = authorization.split("Bearer ", 1)[1].strip()
        secret_key = ensure_auth_secret_key(store.settings)
        payload = verify_access_token(token, secret_key)
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired authentication token",
            )
        return payload

    # Auth Endpoints
    @router.get("/auth/status", response_model=AuthStatusResponse)
    async def get_auth_status(authorization: str | None = Header(default=None)) -> AuthStatusResponse:
        admin_hash = store.settings.get_setting("admin_password_hash")
        setup_required = admin_hash is None

        authenticated = False
        if not setup_required and authorization and authorization.startswith("Bearer "):
            token = authorization.split("Bearer ", 1)[1].strip()
            secret_key = ensure_auth_secret_key(store.settings)
            payload = verify_access_token(token, secret_key)
            authenticated = payload is not None

        return AuthStatusResponse(
            setup_required=setup_required,
            authenticated=authenticated,
        )

    @router.post("/auth/setup", response_model=AuthTokenResponse)
    async def setup_admin_password(req: AuthPasswordRequest) -> AuthTokenResponse:
        admin_hash = store.settings.get_setting("admin_password_hash")
        if admin_hash is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Admin password is already configured. Please log in.",
            )

        hash_hex, salt_hex = hash_password(req.password)
        store.settings.set_setting("admin_password_hash", hash_hex)
        store.settings.set_setting("admin_password_salt", salt_hex)

        secret_key = ensure_auth_secret_key(store.settings)
        token = create_access_token(secret_key)
        return AuthTokenResponse(token=token)

    @router.post("/auth/login", response_model=AuthTokenResponse)
    async def login_admin(req: AuthPasswordRequest) -> AuthTokenResponse:
        admin_hash = store.settings.get_setting("admin_password_hash")
        salt_hex = store.settings.get_setting("admin_password_salt")
        if not admin_hash or not salt_hex:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Admin password not configured yet. Complete setup first.",
            )

        if not verify_password(req.password, admin_hash, salt_hex):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid password",
            )

        secret_key = ensure_auth_secret_key(store.settings)
        token = create_access_token(secret_key)
        return AuthTokenResponse(token=token)

    @router.post("/auth/change-password")
    async def change_password(
        req: ChangePasswordRequest,
        _auth: Any = Depends(require_admin),
    ) -> dict[str, bool]:
        admin_hash = store.settings.get_setting("admin_password_hash")
        salt_hex = store.settings.get_setting("admin_password_salt")
        if not admin_hash or not salt_hex:
            raise HTTPException(status_code=400, detail="Password not initialized.")

        if not verify_password(req.current_password, admin_hash, salt_hex):
            raise HTTPException(status_code=400, detail="Current password is incorrect.")

        new_hash, new_salt = hash_password(req.new_password)
        store.settings.set_setting("admin_password_hash", new_hash)
        store.settings.set_setting("admin_password_salt", new_salt)
        return {"success": True}

    @router.post("/auth/logout")
    async def logout() -> dict[str, bool]:
        return {"success": True}

    # Provider Settings Endpoints
    @router.get("/settings/providers", response_model=list[ProviderItemResponse])
    async def list_providers(_auth: Any = Depends(require_admin)) -> list[ProviderItemResponse]:
        rows = store.settings.list_providers()
        return [
            ProviderItemResponse(
                name=r["name"],
                kind=r["kind"],
                base_url=r["base_url"],
                model=r["model"],
                has_api_key=bool(r["api_key_enc"]),
                is_active=r["is_active"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]

    @router.post("/settings/providers", response_model=ProviderItemResponse)
    async def save_provider(
        req: SaveProviderRequest,
        _auth: Any = Depends(require_admin),
    ) -> ProviderItemResponse:
        master_key = ensure_master_encryption_key(store.settings)
        api_key_enc = None
        if req.api_key and req.api_key.strip():
            api_key_enc = encrypt_secret(req.api_key.strip(), master_key)

        store.settings.save_provider(
            name=req.name,
            kind=req.kind,
            model=req.model,
            base_url=req.base_url,
            api_key_enc=api_key_enc,
            is_active=req.is_active,
        )

        if req.is_active:
            apply_active_provider_to_environment(store)

        saved = store.settings.get_provider(req.name)
        assert saved is not None
        return ProviderItemResponse(
            name=saved["name"],
            kind=saved["kind"],
            base_url=saved["base_url"],
            model=saved["model"],
            has_api_key=bool(saved["api_key_enc"]),
            is_active=saved["is_active"],
            created_at=saved["created_at"],
            updated_at=saved["updated_at"],
        )

    @router.delete("/settings/providers/{name}")
    async def delete_provider(name: str, _auth: Any = Depends(require_admin)) -> dict[str, bool]:
        existing = store.settings.get_provider(name)
        if not existing:
            raise HTTPException(status_code=404, detail=f"Provider {name} not found.")

        if existing["is_active"]:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete the currently active provider. Activate another provider first.",
            )

        store.settings.delete_provider(name)
        return {"success": True}

    @router.post("/settings/providers/{name}/activate")
    async def activate_provider(name: str, _auth: Any = Depends(require_admin)) -> dict[str, Any]:
        existing = store.settings.get_provider(name)
        if not existing:
            raise HTTPException(status_code=404, detail=f"Provider {name} not found.")

        store.settings.set_active_provider(name)
        apply_active_provider_to_environment(store)
        return {"success": True, "active_provider": name}

    @router.post("/settings/providers/test", response_model=TestProviderResponse)
    async def test_provider_connection(
        req: TestProviderRequest,
        _auth: Any = Depends(require_admin),
    ) -> TestProviderResponse:
        master_key = ensure_master_encryption_key(store.settings)

        # Resolve api_key
        api_key = req.api_key
        if not api_key and req.name:
            existing = store.settings.get_provider(req.name)
            if existing and existing.get("api_key_enc"):
                api_key = decrypt_secret(existing["api_key_enc"], master_key)

        if not api_key:
            return TestProviderResponse(
                success=False,
                error="API key is required to test provider connection.",
            )

        start_time = time.time()
        try:
            if req.kind in ("openai", "openai-compatible"):
                endpoint = req.base_url or "https://api.openai.com/v1"
                endpoint = endpoint.rstrip("/")
                test_url = f"{endpoint}/chat/completions"

                payload = {
                    "model": req.model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 5,
                }
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                }

                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(test_url, json=payload, headers=headers)
                    if resp.status_code >= 400:
                        return TestProviderResponse(
                            success=False,
                            error=f"HTTP {resp.status_code}: {resp.text[:300]}",
                        )

            elif req.kind == "google":
                # Google Gemini generateContent probe
                endpoint = req.base_url or "https://generativelanguage.googleapis.com/v1beta"
                endpoint = endpoint.rstrip("/")
                test_url = f"{endpoint}/models/{req.model}:generateContent?key={api_key}"

                payload = {
                    "contents": [{"parts": [{"text": "ping"}]}],
                    "generationConfig": {"maxOutputTokens": 5},
                }

                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(test_url, json=payload)
                    if resp.status_code >= 400:
                        return TestProviderResponse(
                            success=False,
                            error=f"HTTP {resp.status_code}: {resp.text[:300]}",
                        )

            latency = round((time.time() - start_time) * 1000, 1)
            return TestProviderResponse(success=True, latency_ms=latency)

        except Exception as exc:
            return TestProviderResponse(success=False, error=str(exc))

    return router
