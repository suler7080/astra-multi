"""Public provider metadata and references, never API key values."""

import os
import sys
import tempfile
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator
from typing_extensions import Self

from astra_multi.credentials import (
    CredentialStore,
    CredentialStoreError,
    OSCredentialStore,
    validate_secret,
)

ProfileName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
EnvironmentName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]


class ProviderConfigurationError(ValueError):
    pass


class ProviderProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: ProfileName
    kind: Literal["openai", "google", "openai-compatible"]
    model: Annotated[str, Field(min_length=1, pattern=r"\S")]
    base_url: HttpUrl | None = None
    api_key_env: EnvironmentName | None = None
    credential_source: Literal["os", "environment"] = "os"
    json_mode: bool = True

    @model_validator(mode="after")
    def endpoint_contract(self) -> Self:
        url = self.base_url
        if self.credential_source == "environment" and self.api_key_env is None:
            raise ValueError("environment credentials require api_key_env")
        if self.kind == "openai-compatible" and url is None:
            raise ValueError("custom OpenAI-compatible profile requires base_url")
        if url is not None:
            if url.username or url.password or url.query or url.fragment:
                raise ValueError(
                    "base_url cannot contain credentials, query or fragment"
                )
            if url.scheme != "https" and url.host not in {
                "localhost",
                "127.0.0.1",
                "[::1]",
            }:
                raise ValueError(
                    "HTTPS is required except for loopback development endpoints"
                )
        return self


BUILTINS = (
    ProviderProfile(
        name="openai", kind="openai", model="gpt-4o-mini", api_key_env="OPENAI_API_KEY"
    ),
    ProviderProfile(
        name="google",
        kind="google",
        model="gemini-2.0-flash",
        api_key_env="GOOGLE_API_KEY",
    ),
)


class ProviderSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    profiles: list[ProviderProfile] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_profiles(self) -> Self:
        names = [profile.name for profile in self.profiles]
        if len(names) != len(set(names)):
            raise ValueError("profile names must be unique")
        return self

    def effective_profiles(self) -> list[ProviderProfile]:
        profiles = {profile.name: profile for profile in BUILTINS}
        profiles.update({profile.name: profile for profile in self.profiles})
        return list(profiles.values())

    def profile(self, name: str) -> ProviderProfile:
        for profile in self.effective_profiles():
            if profile.name == name:
                return profile
        raise ProviderConfigurationError(f"Unknown provider profile: {name}")


def config_path() -> Path:
    override = os.environ.get("ASTRA_PROVIDER_CONFIG")
    if override:
        return Path(override)
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return root / "AstraMulti" / "providers.json"


class ProviderSettingsRepository:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else config_path()

    def load(self) -> ProviderSettings:
        try:
            payload = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ProviderSettings()
        try:
            return ProviderSettings.model_validate_json(payload)
        except ValueError:
            raise ProviderConfigurationError(
                "Invalid provider settings; only public metadata is allowed"
            ) from None

    def save(self, settings: ProviderSettings) -> None:
        settings = ProviderSettings.model_validate_json(settings.model_dump_json())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent, delete=False
            ) as output:
                temporary = Path(output.name)
                output.write(settings.model_dump_json(indent=2) + "\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


class ProviderManager:
    def __init__(
        self,
        repository: ProviderSettingsRepository,
        credentials: CredentialStore | None = None,
    ) -> None:
        self.repository = repository
        self.credentials = credentials

    def credential_store(self) -> CredentialStore:
        if self.credentials is None:
            self.credentials = OSCredentialStore()
        return self.credentials

    def configure(self, profile: ProviderProfile, secret: str | None = None) -> None:
        if secret is not None and profile.credential_source == "environment":
            raise CredentialStoreError(
                "Environment-only profiles cannot persist an API key"
            )
        settings = self.repository.load()
        updated = ProviderSettings(
            profiles=[p for p in settings.profiles if p.name != profile.name]
            + [profile]
        )
        if secret is None:
            self.repository.save(updated)
            return
        secret = validate_secret(secret)
        store = self.credential_store()
        previous = store.read(profile.name)
        store.write(profile.name, secret)
        try:
            self.repository.save(updated)
        except OSError:
            if previous is None:
                store.delete(profile.name)
            else:
                store.write(profile.name, previous)
            raise

    def remove(self, name: str) -> None:
        settings = self.repository.load()
        updated = ProviderSettings(
            profiles=[p for p in settings.profiles if p.name != name]
        )
        if settings.profile(name).credential_source == "environment":
            self.repository.save(updated)
            return
        store = self.credential_store()
        previous = store.read(name)
        store.delete(name)
        try:
            self.repository.save(updated)
        except OSError:
            if previous is not None:
                store.write(name, previous)
            raise

    def resolve_key(self, profile: ProviderProfile) -> str | None:
        if profile.api_key_env:
            value = os.environ.get(profile.api_key_env)
            if value and value.strip():
                return validate_secret(value)
        if profile.credential_source == "environment":
            return None
        value = self.credential_store().read(profile.name)
        return validate_secret(value) if value is not None else None
