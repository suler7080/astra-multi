"""Provider adapters resolve named profiles and OS/environment credentials."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    ValidationError,
)

from astra_multi.credentials import CredentialStore, CredentialStoreError
from astra_multi.provider_config import (
    ProviderConfigurationError,
    ProviderManager,
    ProviderProfile,
    ProviderSettingsRepository,
)
from astra_multi.schemas import ModelResult

try:
    import openai
    from openai.types.chat import ChatCompletionMessageParam
    from openai.types.shared_params import ResponseFormatJSONObject
except ImportError:
    OPENAI_AVAILABLE = False
else:
    OPENAI_AVAILABLE = True

try:
    from google import genai
    from google.genai import types as google_types
except ImportError:
    GOOGLE_AVAILABLE = False
else:
    GOOGLE_AVAILABLE = True


class ProviderError(Exception):
    def __init__(self, code: str, message: str, provider: str):
        self.code = code
        self.provider = provider
        super().__init__(f"[{provider}] {code}: {message}")


class AuthError(ProviderError):
    pass


class RateLimitError(ProviderError):
    pass


class TimeoutError(ProviderError):
    pass


class SchemaError(ProviderError):
    pass


class ContextOverflowError(ProviderError):
    pass


class GenerationLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: Annotated[str, Field(min_length=1)] | None = None
    timeout: Annotated[float, Field(gt=0, le=3600, allow_inf_nan=False)] = 120
    max_tokens: Annotated[int, Field(gt=0)] | None = None
    max_retries: Annotated[int, Field(ge=0, le=5)] = 0


def _classify_error(provider: str, error: Exception, secret: str = "") -> ProviderError:
    message = str(error).replace(secret, "[REDACTED]") if secret else str(error)
    lower = message.lower()
    if "auth" in lower or "api key" in lower or "401" in lower or "403" in lower:
        return AuthError("AUTH_ERROR", message, provider)
    if "rate" in lower or "429" in lower or "quota" in lower:
        return RateLimitError("RATE_LIMIT", message, provider)
    if "timeout" in lower or "timed out" in lower:
        return TimeoutError("TIMEOUT", message, provider)
    if "context" in lower or "token limit" in lower or "too long" in lower:
        return ContextOverflowError("CONTEXT_OVERFLOW", message, provider)
    return ProviderError("UNKNOWN", message, provider)


json_adapter: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


def _parse_content(
    content: str | None, schema: type[BaseModel] | str | None, provider: str
) -> JsonValue:
    if content is None or not content.strip():
        raise SchemaError("EMPTY_RESPONSE", "Provider returned no text", provider)
    if schema is None:
        return content
    try:
        parsed = json_adapter.validate_python(json.loads(content))
        if isinstance(schema, type):
            return json_adapter.validate_python(
                schema.model_validate(parsed).model_dump(mode="json")
            )
        return parsed
    except (ValueError, ValidationError):
        raise SchemaError(
            "INVALID_SCHEMA",
            "Response does not match the requested JSON/schema",
            provider,
        ) from None


def _messages(
    role: str, messages: list[dict[str, str]], schema: type[BaseModel] | str | None
) -> list[dict[str, str]]:
    system = f"You are a {role}."
    if schema is not None:
        specification = (
            json.dumps(schema.model_json_schema())
            if isinstance(schema, type)
            else schema
        )
        system += f"\nRespond in JSON matching this schema: {specification}"
    return [{"role": "system", "content": system}, *messages]


def _generate_openai(
    profile: ProviderProfile,
    key: str,
    role: str,
    messages: list[dict[str, str]],
    schema: type[BaseModel] | str | None,
    limits: GenerationLimits,
) -> ModelResult:
    if not OPENAI_AVAILABLE:
        raise ProviderError(
            "MISSING_SDK", "Install astra-multi[providers]", profile.name
        )
    typed_messages = TypeAdapter(list[ChatCompletionMessageParam]).validate_python(
        _messages(role, messages, schema)
    )
    with openai.OpenAI(
        api_key=key,
        base_url=str(profile.base_url) if profile.base_url else None,
        timeout=limits.timeout,
        max_retries=limits.max_retries,
    ) as client:
        try:
            response = client.chat.completions.create(
                model=limits.model or profile.model,
                messages=typed_messages,
                response_format=ResponseFormatJSONObject(type="json_object")
                if schema is not None and profile.json_mode
                else openai.omit,
                max_tokens=limits.max_tokens
                if limits.max_tokens is not None
                else openai.omit,
            )
        except openai.APIError as error:
            raise _classify_error(profile.name, error, key) from None
    if not response.choices:
        raise SchemaError(
            "EMPTY_RESPONSE", "Provider returned no choices", profile.name
        )
    content = _parse_content(response.choices[0].message.content, schema, profile.name)
    usage: dict[str, int | None] | None = (
        None
        if response.usage is None
        else {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }
    )
    return ModelResult(
        content=content, usage=usage, model_id=response.model, attempts=1
    )


def _generate_google(
    profile: ProviderProfile,
    key: str,
    role: str,
    messages: list[dict[str, str]],
    schema: type[BaseModel] | str | None,
    limits: GenerationLimits,
) -> ModelResult:
    if not GOOGLE_AVAILABLE:
        raise ProviderError(
            "MISSING_SDK", "Install astra-multi[providers]", profile.name
        )
    options = google_types.HttpOptions(
        timeout=int(limits.timeout * 1000),
        base_url=str(profile.base_url) if profile.base_url else None,
        retry_options=google_types.HttpRetryOptions(attempts=limits.max_retries + 1),
    )
    config = google_types.GenerateContentConfig(
        max_output_tokens=limits.max_tokens,
        response_mime_type="application/json"
        if schema is not None and profile.json_mode
        else None,
    )
    model = limits.model or profile.model
    try:
        with genai.Client(api_key=key, http_options=options) as client:
            prompt = "\n".join(
                f"{message['role']}: {message['content']}"
                for message in _messages(role, messages, schema)
            )
            response = client.models.generate_content(
                model=model, contents=prompt, config=config
            )
    except Exception as error:
        raise _classify_error(profile.name, error, key) from None
    content = _parse_content(response.text, schema, profile.name)
    metadata = response.usage_metadata
    usage = (
        None
        if metadata is None
        else {
            "prompt_tokens": metadata.prompt_token_count,
            "completion_tokens": metadata.candidates_token_count,
            "total_tokens": metadata.total_token_count,
        }
    )
    return ModelResult(
        content=content,
        usage=usage,
        model_id=response.model_version or model,
        attempts=1,
    )


def generate(
    provider: str,
    role: str,
    messages: list[dict[str, str]],
    output_schema: type[BaseModel] | str | None = None,
    tool_specs: list[dict[str, JsonValue]] | None = None,
    limits: GenerationLimits | Mapping[str, object] | None = None,
    *,
    settings: ProviderSettingsRepository | None = None,
    credentials: CredentialStore | None = None,
) -> ModelResult:
    manager = ProviderManager(
        settings if settings is not None else ProviderSettingsRepository(), credentials
    )
    try:
        profile = manager.repository.load().profile(provider)
    except ProviderConfigurationError as error:
        raise ProviderError(
            "UNKNOWN_PROVIDER"
            if str(error).startswith("Unknown")
            else "INVALID_CONFIG",
            str(error),
            provider,
        ) from None
    try:
        key = manager.resolve_key(profile)
    except CredentialStoreError as error:
        raise AuthError("CREDENTIAL_STORE_UNAVAILABLE", str(error), provider) from None
    if key is None:
        raise AuthError(
            "NO_API_KEY",
            "Configure a key in the OS store or the profile's environment variable",
            provider,
        )
    try:
        options = (
            limits
            if isinstance(limits, GenerationLimits)
            else GenerationLimits.model_validate(limits or {})
        )
    except ValidationError:
        raise ProviderError(
            "INVALID_LIMITS", "Invalid generation limits", provider
        ) from None
    adapter = _generate_google if profile.kind == "google" else _generate_openai
    started = time.perf_counter()
    try:
        result = adapter(profile, key, role, messages, output_schema, options)
    except ProviderError:
        raise
    except Exception as error:
        raise _classify_error(profile.name, error, key) from None
    result.provider = profile.name
    result.latency_seconds = time.perf_counter() - started
    result.attempts = 1 if options.max_retries == 0 else None
    return result
