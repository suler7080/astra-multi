"""Unit tests for providers._classify_error bucket selection (P5 SERVER_ERROR)."""

import pytest

from astra_multi.providers import (
    AuthError,
    ProviderError,
    RateLimitError,
    _classify_error,
)


@pytest.mark.parametrize(
    "message",
    [
        # Relay-style 500 unknown server_error / service_unavailable wording.
        "A server error occurred. Please try again.",
        "relay reported service_unavailable for this model",
        "upstream provider glitch (502)",
        "The service is currently experiencing issues (code: 503).",
        "upstream returned 504 for the request",
    ],
)
def test_server_error_bucket(message: str) -> None:
    error = _classify_error("relay", RuntimeError(message))
    assert isinstance(error, ProviderError)
    # SERVER_ERROR uses the base class (no dedicated subclass today).
    assert type(error) is ProviderError
    assert error.code == "SERVER_ERROR"
    assert error.provider == "relay"


def test_auth_message_still_auth_error() -> None:
    error = _classify_error("openai", RuntimeError("Error code: 401 - invalid API key provided"))
    assert isinstance(error, AuthError)
    assert error.code == "AUTH_ERROR"


def test_rate_limit_message_still_rate_limit() -> None:
    error = _classify_error("openai", RuntimeError("429 Too Many Requests"))
    assert isinstance(error, RateLimitError)
    assert error.code == "RATE_LIMIT"


def test_unknown_wording_still_unknown() -> None:
    error = _classify_error("openai", RuntimeError("Network hiccup while relaying the completion."))
    assert type(error) is ProviderError
    assert error.code == "UNKNOWN"


def test_secret_is_redacted_in_message() -> None:
    secret = "sk-synthetic-abc123"
    error = _classify_error(
        "openai", RuntimeError(f"Request failed with key {secret} upstream"), secret=secret
    )
    assert secret not in str(error)
    assert "[REDACTED]" in str(error)
    assert error.code == "UNKNOWN"
