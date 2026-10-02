"""Secret isolation, configuration recovery and independent endpoint routing."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest
from keyring.backends.fail import Keyring as UnavailableKeyring
from pydantic import BaseModel, ConfigDict, ValidationError

from astra_multi import providers
from astra_multi.credentials import CredentialStoreError, OSCredentialStore
from astra_multi.provider_config import (
    ProviderConfigurationError,
    ProviderManager,
    ProviderProfile,
    ProviderSettings,
    ProviderSettingsRepository,
)

if providers.OPENAI_AVAILABLE:
    from openai import OpenAI

if providers.GOOGLE_AVAILABLE:
    from google.genai import Client as GoogleClient
    from google.genai import types as google_types


@dataclass
class MemoryCredentials:
    values: dict[str, str] = field(default_factory=dict)

    def read(self, profile: str) -> str | None:
        return self.values.get(profile)

    def write(self, profile: str, secret: str) -> None:
        self.values[profile] = secret

    def delete(self, profile: str) -> None:
        self.values.pop(profile, None)


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: str


def custom_profile(name: str = "custom", **values: object) -> ProviderProfile:
    return ProviderProfile.model_validate(
        {
            "name": name,
            "kind": "openai-compatible",
            "model": "vendor/model",
            "base_url": "https://custom.example/v1",
            **values,
        }
    )


def test_secret_rotation_restart_and_removal(tmp_path: Path) -> None:
    repository = ProviderSettingsRepository(tmp_path / "profiles.json")
    credentials = MemoryCredentials()
    manager = ProviderManager(repository, credentials)
    manager.configure(custom_profile(), "synthetic-first-key")
    manager.configure(custom_profile(), "synthetic-rotated-key")
    reopened = ProviderManager(ProviderSettingsRepository(repository.path), credentials)
    assert (
        reopened.resolve_key(reopened.repository.load().profile("custom"))
        == "synthetic-rotated-key"
    )
    assert "synthetic-" not in repository.path.read_text()
    assert [
        profile.name for profile in reopened.repository.load().effective_profiles()
    ] == ["openai", "google", "custom"]
    reopened.remove("custom")
    assert credentials.read("custom") is None
    with pytest.raises(ProviderConfigurationError):
        reopened.repository.load().profile("custom")


def test_failed_metadata_write_restores_previous_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = ProviderSettingsRepository(tmp_path / "profiles.json")
    credentials = MemoryCredentials()
    manager = ProviderManager(repository, credentials)
    manager.configure(custom_profile(), "old-test-key")
    original = repository.path.read_bytes()

    def fail(settings: ProviderSettings) -> None:
        raise OSError("disk failure")

    monkeypatch.setattr(repository, "save", fail)
    with pytest.raises(OSError):
        manager.configure(custom_profile(model="different-model"), "new-test-key")
    assert credentials.read("custom") == "old-test-key"
    assert repository.path.read_bytes() == original
    with pytest.raises(OSError):
        manager.remove("custom")
    assert credentials.read("custom") == "old-test-key"


@pytest.mark.parametrize(
    "url",
    [
        "https://user:password@example.com/v1",
        "https://example.com/v1?key=secret",
        "https://example.com/v1#secret",
        "http://remote.example/v1",
        "file:///secret",
    ],
)
def test_config_rejects_secret_bearing_or_insecure_url(url: str) -> None:
    with pytest.raises(ValidationError):
        custom_profile(base_url=url)


def test_config_rejects_api_key_fields_without_echoing_key(tmp_path: Path) -> None:
    repository = ProviderSettingsRepository(tmp_path / "profiles.json")
    repository.path.write_text('{"profiles":[],"api_key":"synthetic-secret"}')
    with pytest.raises(ProviderConfigurationError) as caught:
        repository.load()
    assert "synthetic-secret" not in str(caught.value)
    with pytest.raises(ValidationError):
        ProviderSettings(profiles=[custom_profile(), custom_profile()])


def test_environment_only_never_falls_back_to_old_os_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    credentials = MemoryCredentials({"custom": "old-os-key"})
    manager = ProviderManager(
        ProviderSettingsRepository(tmp_path / "profiles.json"), credentials
    )
    profile = custom_profile(
        api_key_env="TEST_PROFILE_API_KEY", credential_source="environment"
    )
    manager.configure(profile)
    monkeypatch.delenv("TEST_PROFILE_API_KEY", raising=False)
    assert manager.resolve_key(profile) is None
    monkeypatch.setenv("TEST_PROFILE_API_KEY", "new-session-key")
    assert manager.resolve_key(profile) == "new-session-key"
    manager.remove(profile.name)
    assert credentials.read(profile.name) == "old-os-key"


def test_unavailable_or_plaintext_keyring_is_rejected() -> None:
    with pytest.raises(CredentialStoreError, match="Secure OS keyring unavailable"):
        OSCredentialStore(UnavailableKeyring())


def test_environment_only_api_cannot_persist_secret(tmp_path: Path) -> None:
    credentials = MemoryCredentials({})
    manager = ProviderManager(
        ProviderSettingsRepository(tmp_path / "providers.json"), credentials
    )
    profile = custom_profile(
        credential_source="environment", api_key_env="TEST_API_KEY"
    )
    with pytest.raises(CredentialStoreError, match="Environment-only"):
        manager.configure(profile, "temporary-key-must-stay-temporary")
    assert credentials.values == {}
    assert not manager.repository.path.exists()


@pytest.mark.skipif(not providers.OPENAI_AVAILABLE, reason="install providers extra")
def test_endpoint_without_native_json_mode_still_validates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = ProviderSettingsRepository(tmp_path / "providers.json")
    credentials = MemoryCredentials({})
    ProviderManager(repository, credentials).configure(
        custom_profile(json_mode=False), "synthetic-key"
    )

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert "response_format" not in body
        assert '"additionalProperties": false' in body["messages"][0]["content"]
        return httpx.Response(
            200,
            json={
                "id": "completion",
                "object": "chat.completion",
                "created": 1,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": '{"status":"ok","extra":"rejected"}',
                        },
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    configure_openai_transport(monkeypatch, httpx.MockTransport(handle))
    with pytest.raises(providers.SchemaError):
        providers.generate(
            "custom",
            "planner",
            [{"role": "user", "content": "return JSON"}],
            Payload,
            settings=repository,
            credentials=credentials,
        )


def configure_openai_transport(
    monkeypatch: pytest.MonkeyPatch, handler: httpx.MockTransport
) -> None:
    def client(
        *, api_key: str, base_url: str | None, timeout: float, max_retries: int
    ) -> OpenAI:
        return OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            http_client=httpx.Client(transport=handler),
        )

    monkeypatch.setattr(providers.openai, "OpenAI", client)


@pytest.mark.skipif(not providers.OPENAI_AVAILABLE, reason="install providers extra")
def test_custom_transport_uses_own_key_endpoint_and_validates_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    credentials = MemoryCredentials()
    repository = ProviderSettingsRepository(tmp_path / "profiles.json")
    manager = ProviderManager(repository, credentials)
    manager.configure(custom_profile("one"), "test-key-one")
    manager.configure(
        custom_profile(
            "two", base_url="https://second.example/v1", model="other/model"
        ),
        "test-key-two",
    )
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        model = json.loads(request.content)["model"]
        return httpx.Response(
            200,
            json={
                "id": "test",
                "object": "chat.completion",
                "created": 1,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": '{"status":"ok"}'},
                    }
                ],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 3,
                    "total_tokens": 8,
                },
            },
        )

    configure_openai_transport(monkeypatch, httpx.MockTransport(handler))
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://unrelated.example/v1")
    for name in ("one", "two"):
        result = providers.generate(
            name,
            "planner",
            [{"role": "user", "content": "JSON please"}],
            Payload,
            settings=repository,
            credentials=credentials,
            limits={"timeout": 2, "max_tokens": 50},
        )
        assert result.content == {"status": "ok"}
        assert result.usage == {
            "prompt_tokens": 5,
            "completion_tokens": 3,
            "total_tokens": 8,
        }
    assert [request.url.host for request in captured] == [
        "custom.example",
        "second.example",
    ]
    assert [request.headers["authorization"] for request in captured] == [
        "Bearer test-key-one",
        "Bearer test-key-two",
    ]
    assert all(request.url.path == "/v1/chat/completions" for request in captured)
    assert json.loads(captured[0].content)["response_format"] == {"type": "json_object"}
    assert json.loads(captured[0].content)["max_tokens"] == 50


@pytest.mark.parametrize("content", ['{"different":"ok"}', "not JSON", ""])
@pytest.mark.skipif(not providers.OPENAI_AVAILABLE, reason="install providers extra")
def test_adapter_rejects_invalid_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    repository = ProviderSettingsRepository(tmp_path / "profiles.json")
    credentials = MemoryCredentials({"custom": "test-key"})
    ProviderManager(repository, credentials).configure(custom_profile())
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "id": "test",
                "created": 1,
                "model": "vendor/model",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": content},
                    }
                ],
            },
        )
    )
    configure_openai_transport(monkeypatch, transport)
    with pytest.raises(providers.SchemaError):
        providers.generate(
            "custom",
            "planner",
            [{"role": "user", "content": "test"}],
            Payload,
            settings=repository,
            credentials=credentials,
        )


@pytest.mark.parametrize(
    "status,expected", [(401, providers.AuthError), (429, providers.RateLimitError)]
)
@pytest.mark.skipif(not providers.OPENAI_AVAILABLE, reason="install providers extra")
def test_sdk_error_is_classified_and_key_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    expected: type[providers.ProviderError],
) -> None:
    repository = ProviderSettingsRepository(tmp_path / "profiles.json")
    credentials = MemoryCredentials({"custom": "synthetic-sensitive-key"})
    ProviderManager(repository, credentials).configure(custom_profile())
    configure_openai_transport(
        monkeypatch,
        httpx.MockTransport(
            lambda request: httpx.Response(
                status,
                json={
                    "error": {
                        "message": "synthetic-sensitive-key rejected",
                        "type": "error",
                    }
                },
            )
        ),
    )
    with pytest.raises(expected) as caught:
        providers.generate(
            "custom",
            "planner",
            [{"role": "user", "content": "test"}],
            settings=repository,
            credentials=credentials,
        )
    assert "synthetic-sensitive-key" not in str(caught.value)
    assert "[REDACTED]" in str(caught.value)


@pytest.mark.skipif(not providers.OPENAI_AVAILABLE, reason="install providers extra")
def test_sdk_timeout_is_classified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = ProviderSettingsRepository(tmp_path / "profiles.json")
    credentials = MemoryCredentials({"custom": "test-key"})
    ProviderManager(repository, credentials).configure(custom_profile())

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    configure_openai_transport(monkeypatch, httpx.MockTransport(timeout))
    with pytest.raises(providers.TimeoutError):
        providers.generate(
            "custom",
            "planner",
            [{"role": "user", "content": "test"}],
            settings=repository,
            credentials=credentials,
        )


@pytest.mark.skipif(not providers.GOOGLE_AVAILABLE, reason="install providers extra")
def test_google_uses_native_protocol_and_preserves_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [{"text": '{"status":"ok"}'}],
                        },
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 7,
                    "candidatesTokenCount": 4,
                    "totalTokenCount": 11,
                },
            },
        )

    def client(*, api_key: str, http_options: google_types.HttpOptions) -> GoogleClient:
        assert http_options.timeout == 2000
        assert (
            http_options.retry_options is not None
            and http_options.retry_options.attempts == 1
        )
        options = http_options.model_copy(
            update={"client_args": {"transport": httpx.MockTransport(handler)}}
        )
        return GoogleClient(api_key=api_key, http_options=options)

    monkeypatch.setattr(providers.genai, "Client", client)
    repository = ProviderSettingsRepository(tmp_path / "profiles.json")
    credentials = MemoryCredentials({"google-test": "google-test-key"})
    profile = ProviderProfile(
        name="google-test",
        kind="google",
        model="gemini-test",
        base_url="https://gemini.example",
    )
    ProviderManager(repository, credentials).configure(profile)
    result = providers.generate(
        profile.name,
        "reviewer",
        [{"role": "user", "content": "JSON please"}],
        Payload,
        settings=repository,
        credentials=credentials,
        limits={"timeout": 2},
    )
    assert result.content == {"status": "ok"}
    assert result.usage == {
        "prompt_tokens": 7,
        "completion_tokens": 4,
        "total_tokens": 11,
    }
    assert requests[0].headers["x-goog-api-key"] == "google-test-key"
    assert requests[0].url.host == "gemini.example"
    assert ":generateContent" in requests[0].url.path


def test_cli_environment_profile_survives_restart_and_does_not_print_key(
    tmp_path: Path,
) -> None:
    config = tmp_path / "profiles.json"
    command = [
        sys.executable,
        "-m",
        "astra_multi.provider_cli",
        "--config",
        str(config),
    ]
    environment = {**os.environ, "TEST_CLI_KEY": "synthetic-cli-secret"}
    result = subprocess.run(
        [
            *command,
            "set",
            "custom",
            "--kind",
            "openai-compatible",
            "--model",
            "vendor/model",
            "--base-url",
            "https://custom.example/v1",
            "--key-env",
            "TEST_CLI_KEY",
            "--env-only",
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    listing = subprocess.run(
        [*command, "list"], env=environment, capture_output=True, text=True, check=True
    )
    assert '"name":"custom"' in listing.stdout
    assert (
        "synthetic-cli-secret"
        not in result.stdout
        + result.stderr
        + listing.stdout
        + listing.stderr
        + config.read_text()
    )
    subprocess.run(
        [*command, "remove", "custom"],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "custom" not in config.read_text()


@pytest.mark.skipif(
    os.name != "nt", reason="requires native Windows Credential Manager"
)
def test_windows_native_credential_store_restart_rotation_removal(
    tmp_path: Path,
) -> None:
    name = "native-test-" + uuid.uuid4().hex
    store = OSCredentialStore()
    repository = ProviderSettingsRepository(tmp_path / "providers.json")
    manager = ProviderManager(repository, store)
    script = "from astra_multi.credentials import OSCredentialStore; import sys; assert OSCredentialStore().read(sys.argv[1]) == sys.argv[2]"
    try:
        for secret in ("synthetic-native-first", "synthetic-native-rotated"):
            manager.configure(custom_profile(name), secret)
            subprocess.run(
                [sys.executable, "-c", script, name, secret],
                check=True,
                capture_output=True,
                text=True,
            )
            assert secret not in repository.path.read_text()
        manager.remove(name)
        assert store.read(name) is None
        assert name not in repository.path.read_text()
    finally:
        store.delete(name)
