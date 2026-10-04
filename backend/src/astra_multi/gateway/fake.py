"""Fake providers for testing model gateway behavior."""

import time
from dataclasses import dataclass
from typing import Any, Union

from astra_multi.providers import AuthError, ProviderError, RateLimitError, SchemaError
from astra_multi.schemas import ModelResult


@dataclass
class FakeProviderConfig:
    """Configuration for fake provider behavior."""
    should_fail: bool = False
    error_type: str = "UNKNOWN"
    delay_seconds: float = 0.0
    empty_response: bool = False
    invalid_json: bool = False
    rate_limit_after: int = 999  # Fail after this many calls


class FakeProvider:
    """Fake provider for testing gateway behavior."""

    def __init__(self, config: FakeProviderConfig | None = None) -> None:
        self.config = config or FakeProviderConfig()
        self._call_count = 0

    def generate(
        self,
        role: str,
        messages: list[dict[str, str]],
        output_schema: Any = None,
        **kwargs: Any,
    ) -> ModelResult:
        """Generate a fake model response."""
        self._call_count += 1

        # Simulate delay
        if self.config.delay_seconds > 0:
            time.sleep(self.config.delay_seconds)

        # Check for rate limit
        if self._call_count > self.config.rate_limit_after:
            raise RateLimitError(
                "RATE_LIMIT", "Fake rate limit exceeded", "fake"
            )

        # Check for failure
        if self.config.should_fail:
            if self.config.error_type == "AUTH":
                raise AuthError("AUTH_ERROR", "Fake auth error", "fake")
            elif self.config.error_type == "SCHEMA":
                raise SchemaError("INVALID_SCHEMA", "Fake schema error", "fake")
            else:
                raise ProviderError(
                    self.config.error_type, "Fake provider error", "fake"
                )

        # Check for empty response
        if self.config.empty_response:
            raise SchemaError("EMPTY_RESPONSE", "Fake empty response", "fake")

        # Generate fake content
        content: Union[str, dict[str, Any]]
        if output_schema is not None:
            if self.config.invalid_json:
                content = "not valid json"
            else:
                content = {"findings": ["fake finding"], "risks": [], "assumptions": []}
        else:
            content = "Fake response content"

        return ModelResult(
            content=content,
            usage={
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            },
            model_id="fake-model",
            attempts=1,
            provider="fake",
            latency_seconds=self.config.delay_seconds,
        )
