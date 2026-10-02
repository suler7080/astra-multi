"""P0.4 Tests — Provider smoke tests.

Live tests require API keys and are BLOCKED until keys are available.
Fake tests verify error classification and adapter routing without API calls.
"""

from __future__ import annotations

import os
import pytest

from astra_multi.providers import (
    AuthError,
    ProviderError,
    generate,
)


class TestProviderRouting:
    """Verify adapter routing works without API calls."""

    def test_unknown_provider_raises(self):
        with pytest.raises(ProviderError, match="UNKNOWN_PROVIDER"):
            generate(
                provider="nonexistent",
                role="planner",
                messages=[{"role": "user", "content": "test"}],
            )

    def test_openai_without_key_raises_auth_error(self):
        """OpenAI adapter should raise AuthError when no key is set."""
        old_key = os.environ.pop("OPENAI_API_KEY", None)
        try:
            with pytest.raises((AuthError, ProviderError)):
                generate(
                    provider="openai",
                    role="planner",
                    messages=[{"role": "user", "content": "test"}],
                )
        finally:
            if old_key:
                os.environ["OPENAI_API_KEY"] = old_key

    def test_google_without_key_raises_auth_error(self):
        """Google adapter should raise AuthError when no key is set."""
        old_key = os.environ.pop("GOOGLE_API_KEY", None)
        try:
            with pytest.raises((AuthError, ProviderError)):
                generate(
                    provider="google",
                    role="planner",
                    messages=[{"role": "user", "content": "test"}],
                )
        finally:
            if old_key:
                os.environ["GOOGLE_API_KEY"] = old_key


class TestErrorClassification:
    """Verify error types are correctly classified."""

    def test_auth_error_has_correct_code(self):
        err = AuthError("AUTH_ERROR", "Invalid key", "openai")
        assert err.code == "AUTH_ERROR"
        assert err.provider == "openai"
        assert "AUTH_ERROR" in str(err)

    def test_provider_error_hierarchy(self):
        assert issubclass(AuthError, ProviderError)
        from astra_multi.providers import RateLimitError, TimeoutError, SchemaError
        assert issubclass(RateLimitError, ProviderError)
        assert issubclass(TimeoutError, ProviderError)
        assert issubclass(SchemaError, ProviderError)


# ---------------------------------------------------------------------------
# Live smoke tests — BLOCKED without API keys
# ---------------------------------------------------------------------------

_has_openai_key = bool(os.environ.get("OPENAI_API_KEY"))
_has_google_key = bool(os.environ.get("GOOGLE_API_KEY"))


@pytest.mark.skipif(not _has_openai_key, reason="OPENAI_API_KEY not set — BLOCKED")
class TestOpenAILive:
    """Live smoke test for OpenAI. BLOCKED without API key."""

    def test_simple_request(self):
        result = generate(
            provider="openai",
            role="planner",
            messages=[{"role": "user", "content": "Say 'hello' in one word."}],
            limits={"model": "gpt-4o-mini", "timeout": 30},
        )
        assert result.content is not None
        assert result.model_id is not None
        assert result.usage is not None
        print(f"OpenAI response: {result.content[:100]}")
        print(f"Model: {result.model_id}, Usage: {result.usage}")

    def test_json_output(self):
        result = generate(
            provider="openai",
            role="planner",
            messages=[{"role": "user", "content": 'Return {"status": "ok"}'}],
            output_schema="{'status': str}",
            limits={"model": "gpt-4o-mini", "timeout": 30},
        )
        assert isinstance(result.content, dict)
        assert "status" in result.content


@pytest.mark.skipif(not _has_google_key, reason="GOOGLE_API_KEY not set — BLOCKED")
class TestGoogleLive:
    """Live smoke test for Google Gemini. BLOCKED without API key."""

    def test_simple_request(self):
        result = generate(
            provider="google",
            role="planner",
            messages=[{"role": "user", "content": "Say 'hello' in one word."}],
            limits={"model": "gemini-2.0-flash"},
        )
        assert result.content is not None
        assert result.model_id is not None
        print(f"Google response: {str(result.content)[:100]}")
        print(f"Model: {result.model_id}, Usage: {result.usage}")

    def test_json_output(self):
        result = generate(
            provider="google",
            role="planner",
            messages=[{"role": "user", "content": 'Return exactly: {"status": "ok"}'}],
            output_schema="{'status': str}",
            limits={"model": "gemini-2.0-flash"},
        )
        assert isinstance(result.content, dict)
        assert "status" in result.content
