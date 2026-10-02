"""Provider adapters — thin wrappers around LLM provider SDKs.

Contract: generate(role, messages, output_schema, tool_specs, limits) -> ModelResult
Domain schema does NOT import SDK provider.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from astra_multi.schemas import ModelResult


class ProviderError(Exception):
    """Base class for provider errors."""

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


def _classify_error(provider: str, e: Exception) -> ProviderError:
    """Classify an exception into a specific error type."""
    msg = str(e).lower()
    if "auth" in msg or "api key" in msg or "401" in msg or "403" in msg:
        return AuthError("AUTH_ERROR", str(e), provider)
    if "rate" in msg or "429" in msg or "quota" in msg:
        return RateLimitError("RATE_LIMIT", str(e), provider)
    if "timeout" in msg or "timed out" in msg:
        return TimeoutError("TIMEOUT", str(e), provider)
    if "context" in msg or "token limit" in msg or "too long" in msg:
        return ContextOverflowError("CONTEXT_OVERFLOW", str(e), provider)
    return ProviderError("UNKNOWN", str(e), provider)


# ---------------------------------------------------------------------------
# OpenAI adapter
# ---------------------------------------------------------------------------

def _generate_openai(
    role: str,
    messages: list[dict[str, str]],
    output_schema: type | None = None,
    tool_specs: list[Any] | None = None,
    limits: dict[str, Any] | None = None,
) -> ModelResult:
    """OpenAI provider adapter."""
    try:
        import openai
    except ImportError:
        raise ProviderError(
            "MISSING_SDK", "openai package not installed", "openai"
        )

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise AuthError("NO_API_KEY", "OPENAI_API_KEY not set", "openai")

    model = limits.get("model", "gpt-4o-mini") if limits else "gpt-4o-mini"
    timeout = limits.get("timeout", 120) if limits else 120

    client = openai.OpenAI(api_key=api_key, timeout=timeout)

    start = time.time()
    try:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": f"You are a {role}."}, *messages],
        }

        if output_schema:
            kwargs["response_format"] = {"type": "json_object"}
            messages_with_schema = list(kwargs["messages"])
            messages_with_schema[0]["content"] += (
                f"\nRespond in JSON matching this schema: {output_schema}"
            )
            kwargs["messages"] = messages_with_schema

        response = client.chat.completions.create(**kwargs)
        latency = time.time() - start

        content = response.choices[0].message.content
        usage = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        # Parse JSON if schema was requested
        if output_schema:
            try:
                content = json.loads(content)
            except json.JSONDecodeError as e:
                raise SchemaError("INVALID_JSON", f"Response not valid JSON: {e}", "openai")

        return ModelResult(
            content=content,
            usage=usage,
            model_id=response.model,
            attempts=1,
        )
    except openai.AuthenticationError as e:
        raise AuthError("AUTH_ERROR", str(e), "openai")
    except openai.RateLimitError as e:
        raise RateLimitError("RATE_LIMIT", str(e), "openai")
    except openai.APITimeoutError as e:
        raise TimeoutError("TIMEOUT", str(e), "openai")
    except openai.APIError as e:
        raise _classify_error("openai", e)


# ---------------------------------------------------------------------------
# Google Gemini adapter
# ---------------------------------------------------------------------------

def _generate_google(
    role: str,
    messages: list[dict[str, str]],
    output_schema: type | None = None,
    tool_specs: list[Any] | None = None,
    limits: dict[str, Any] | None = None,
) -> ModelResult:
    """Google Gemini provider adapter."""
    try:
        from google import genai
    except ImportError:
        raise ProviderError(
            "MISSING_SDK", "google-genai package not installed", "google"
        )

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise AuthError("NO_API_KEY", "GOOGLE_API_KEY not set", "google")

    model = limits.get("model", "gemini-2.0-flash") if limits else "gemini-2.0-flash"

    client = genai.Client(api_key=api_key)

    start = time.time()
    try:
        prompt = f"You are a {role}.\n"
        for msg in messages:
            prompt += f"\n{msg['role']}: {msg['content']}"

        if output_schema:
            prompt += f"\n\nRespond in JSON matching this schema: {output_schema}"

        response = client.models.generate_content(
            model=model,
            contents=prompt,
        )
        latency = time.time() - start

        content = response.text
        usage = {}
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            um = response.usage_metadata
            usage = {
                "prompt_tokens": getattr(um, "prompt_token_count", 0) or 0,
                "completion_tokens": getattr(um, "candidates_token_count", 0) or 0,
                "total_tokens": getattr(um, "total_token_count", 0) or 0,
            }

        if output_schema:
            try:
                content = json.loads(content)
            except json.JSONDecodeError as e:
                raise SchemaError("INVALID_JSON", f"Response not valid JSON: {e}", "google")

        return ModelResult(
            content=content,
            usage=usage,
            model_id=model,
            attempts=1,
        )
    except Exception as e:
        if isinstance(e, ProviderError):
            raise
        raise _classify_error("google", e)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

PROVIDERS = {
    "openai": _generate_openai,
    "google": _generate_google,
}


def generate(
    provider: str,
    role: str,
    messages: list[dict[str, str]],
    output_schema: type | None = None,
    tool_specs: list[Any] | None = None,
    limits: dict[str, Any] | None = None,
) -> ModelResult:
    """Route to the correct provider adapter."""
    adapter = PROVIDERS.get(provider)
    if adapter is None:
        raise ProviderError("UNKNOWN_PROVIDER", f"Unknown provider: {provider}", provider)
    return adapter(role, messages, output_schema, tool_specs, limits)
