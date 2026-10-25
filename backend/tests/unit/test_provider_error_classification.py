"""Unit tests for providers._classify_error bucket selection (P5 SERVER_ERROR)."""

import pytest

from astra_multi.providers import (
    AuthError,
    ContextOverflowError,
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


class _StatusError(Exception):
    """Duck-typed stand-in for openai APIStatusError-style status exceptions."""

    def __init__(self, status_code: int, message: str = "upstream provider failure"):
        super().__init__(message)
        self.status_code = status_code


class _Response:
    def __init__(self, status_code: int):
        self.status_code = status_code


class _ResponseStatusError(Exception):
    """Duck-typed stand-in for httpx.HTTPStatusError (status on .response)."""

    def __init__(self, status_code: int, message: str = "upstream provider failure"):
        super().__init__(message)
        self.response = _Response(status_code)


# P8: message containing a near-miss number that includes the token count
# must still land in CONTEXT_OVERFLOW, never in SERVER_ERROR.
def test_context_overflow_message_is_not_server_error() -> None:
    error = _classify_error("openai", RuntimeError("context length 1503 tokens exceeded"))
    assert isinstance(error, ContextOverflowError)
    assert error.code == "CONTEXT_OVERFLOW"


@pytest.mark.parametrize(
    "message",
    [
        "error 5030 while generating",
        "1503 units consumed before the failure",
    ],
)
def test_lookalike_numbers_are_not_server_error(message: str) -> None:
    error = _classify_error("relay", RuntimeError(message))
    assert type(error) is ProviderError
    assert error.code == "UNKNOWN"


@pytest.mark.parametrize(
    "message",
    [
        "HTTP 502 Bad Gateway",
        "HTTP 503",
        "HTTP 504",
    ],
)
def test_real_5xx_messages_are_server_error(message: str) -> None:
    error = _classify_error("relay", RuntimeError(message))
    assert type(error) is ProviderError
    assert error.code == "SERVER_ERROR"
    assert error.provider == "relay"


@pytest.mark.parametrize("status", [500, 502, 503, 504, 599])
def test_status_code_attribute_is_server_error(status: int) -> None:
    error = _classify_error("openai", _StatusError(status))
    assert type(error) is ProviderError
    assert error.code == "SERVER_ERROR"


def test_nested_response_status_code_is_server_error() -> None:
    error = _classify_error("relay", _ResponseStatusError(502))
    assert type(error) is ProviderError
    assert error.code == "SERVER_ERROR"


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429])
def test_non_5xx_status_attribute_is_not_server_error(status: int) -> None:
    error = _classify_error("relay", _StatusError(status, "resource not found"))
    assert type(error) is ProviderError
    assert error.code == "UNKNOWN"
