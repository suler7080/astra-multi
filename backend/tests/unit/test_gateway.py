"""Unit tests for model gateway components."""

import time
from dataclasses import dataclass
from typing import Any, Union

import pytest

from astra_multi.gateway.model_gateway import (
    BudgetExceededError,
    BudgetHook,
    GatewayConfig,
    ModelGateway,
)
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


def test_budget_hook() -> None:
    hook = BudgetHook(max_calls=2, max_total_tokens=1000, max_total_cost_usd=1.0)

    # First call should pass
    hook.check_reservation(estimated_tokens=500, estimated_cost_usd=0.5)
    hook.record_usage(used_tokens=500, used_cost_usd=0.5)

    # Second call should pass
    hook.check_reservation(estimated_tokens=500, estimated_cost_usd=0.5)
    hook.record_usage(used_tokens=500, used_cost_usd=0.5)

    # Third call should fail (max calls exceeded)
    with pytest.raises(BudgetExceededError, match="Max calls"):
        hook.check_reservation(estimated_tokens=100, estimated_cost_usd=0.1)

    # Check stats
    stats = hook.get_stats()
    assert stats["used_tokens"] == 1000
    assert stats["used_cost_usd"] == 1.0
    assert stats["call_count"] == 2


def test_budget_hook_token_limit() -> None:
    hook = BudgetHook(max_total_tokens=100)

    # Should pass
    hook.check_reservation(estimated_tokens=50)
    hook.record_usage(used_tokens=50)

    # Should exceed
    with pytest.raises(BudgetExceededError, match="Max tokens"):
        hook.check_reservation(estimated_tokens=60)


def test_budget_hook_cost_limit() -> None:
    hook = BudgetHook(max_total_cost_usd=0.5)

    # Should pass
    hook.check_reservation(estimated_cost_usd=0.3)
    hook.record_usage(used_cost_usd=0.3)

    # Should exceed
    with pytest.raises(BudgetExceededError, match="Max cost"):
        hook.check_reservation(estimated_cost_usd=0.3)


def test_fake_provider() -> None:
    provider = FakeProvider()

    # Normal call
    result = provider.generate("planner", [{"role": "user", "content": "test"}])
    assert result.content == "Fake response content"
    assert result.provider == "fake"
    assert result.usage is not None
    assert result.usage["total_tokens"] == 150


def test_fake_provider_failure() -> None:
    config = FakeProviderConfig(should_fail=True, error_type="AUTH")
    provider = FakeProvider(config)

    with pytest.raises(AuthError):
        provider.generate("planner", [{"role": "user", "content": "test"}])


def test_fake_provider_schema_error() -> None:
    config = FakeProviderConfig(should_fail=True, error_type="SCHEMA")
    provider = FakeProvider(config)

    with pytest.raises(SchemaError):
        provider.generate("planner", [{"role": "user", "content": "test"}])


def test_fake_provider_empty_response() -> None:
    config = FakeProviderConfig(empty_response=True)
    provider = FakeProvider(config)

    with pytest.raises(SchemaError, match="EMPTY_RESPONSE"):
        provider.generate("planner", [{"role": "user", "content": "test"}])


def test_fake_provider_rate_limit() -> None:
    config = FakeProviderConfig(rate_limit_after=1)
    provider = FakeProvider(config)

    # First call should pass
    provider.generate("planner", [{"role": "user", "content": "test"}])

    # Second call should rate limit
    with pytest.raises(RateLimitError):
        provider.generate("planner", [{"role": "user", "content": "test"}])


def test_fake_provider_with_schema() -> None:
    provider = FakeProvider()

    result = provider.generate(
        "planner",
        [{"role": "user", "content": "test"}],
        output_schema=dict,  # Just for testing
    )
    assert isinstance(result.content, dict)
    assert "findings" in result.content


def test_gateway_config() -> None:
    config = GatewayConfig(
        default_max_retries=3,
        default_timeout=60,
        enable_output_repair=False,
        enable_budget_hook=False,
    )
    assert config.default_max_retries == 3
    assert config.default_timeout == 60
    assert not config.enable_output_repair
    assert not config.enable_budget_hook


def test_gateway_initialization() -> None:
    gateway = ModelGateway()
    assert gateway.config.default_max_retries == 2
    assert gateway.config.default_timeout == 120
    assert gateway.config.enable_output_repair
    assert gateway.budget_hook is None

    custom_config = GatewayConfig(default_max_retries=5)
    gateway = ModelGateway(config=custom_config)
    assert gateway.config.default_max_retries == 5


def test_gateway_with_budget_hook() -> None:
    budget = BudgetHook(max_calls=1)
    gateway = ModelGateway(budget_hook=budget)

    assert gateway.budget_hook is budget
    assert gateway.config.enable_budget_hook
