"""Tests for gateway retry behavior and error handling."""

import pytest

from astra_multi.gateway.fake import FakeProvider
from astra_multi.gateway.model_gateway import (
    AttemptTrace,
    BudgetExceededError,
    BudgetHook,
    GatewayConfig,
    ModelGateway,
)


def test_max_retries_default():
    """Default max retries should be 2 (3 attempts total)."""
    gateway = ModelGateway()
    assert gateway.config.default_max_retries == 2


def test_custom_max_retries():
    """Custom max retries should be respected."""
    gateway = ModelGateway(config=GatewayConfig(default_max_retries=5))
    assert gateway.config.default_max_retries == 5


def test_default_timeout():
    """Default timeout should be 120 seconds."""
    gateway = ModelGateway()
    assert gateway.config.default_timeout == 120


def test_custom_timeout():
    """Custom timeout should be respected."""
    gateway = ModelGateway(config=GatewayConfig(default_timeout=60))
    assert gateway.config.default_timeout == 60


def test_attempt_trace_structure():
    """Attempt trace should contain all required fields."""
    trace = AttemptTrace(
        attempt_number=1,
        timestamp=1234567890.0,
        provider="fake",
        model_id="fake-model",
        error="Test error",
        latency_seconds=1.5,
        tokens_used=100,
    )

    assert trace.attempt_number == 1
    assert trace.timestamp == 1234567890.0
    assert trace.provider == "fake"
    assert trace.model_id == "fake-model"
    assert trace.error == "Test error"
    assert trace.latency_seconds == 1.5
    assert trace.tokens_used == 100


def test_attempt_trace_optional_fields():
    """Optional fields in attempt trace should be None if not provided."""
    trace = AttemptTrace(
        attempt_number=1,
        timestamp=1234567890.0,
        provider="fake",
    )

    assert trace.model_id is None
    assert trace.error is None
    assert trace.latency_seconds is None
    assert trace.tokens_used is None


def test_clear_traces():
    """Clear traces should remove all attempt traces."""
    gateway = ModelGateway()

    # Add some traces manually
    gateway._attempt_traces.append(
        AttemptTrace(attempt_number=1, timestamp=0.0, provider="fake")
    )
    gateway._attempt_traces.append(
        AttemptTrace(attempt_number=2, timestamp=1.0, provider="fake")
    )

    assert len(gateway.get_attempt_traces()) == 2

    gateway.clear_traces()

    assert len(gateway.get_attempt_traces()) == 0


def test_budget_enforcement_on_call():
    """Budget should be checked before call and enforced."""
    budget = BudgetHook(max_calls=1)
    gateway = ModelGateway(budget_hook=budget)

    import astra_multi.gateway.model_gateway as gateway_module
    original_generate = gateway_module.generate

    def fake_generate(*args, **kwargs):
        from astra_multi.schemas import ModelResult
        return ModelResult(content="test", usage={"total_tokens": 100})

    gateway_module.generate = fake_generate

    try:
        # First call should succeed
        gateway.call("fake", "planner", [])

        # Second call should fail
        with pytest.raises(BudgetExceededError, match="Max calls"):
            gateway.call("fake", "planner", [])
    finally:
        gateway_module.generate = original_generate


def test_budget_records_usage():
    """Budget should record actual usage after successful call."""
    budget = BudgetHook(max_calls=10)
    gateway = ModelGateway(budget_hook=budget)

    import astra_multi.gateway.model_gateway as gateway_module
    original_generate = gateway_module.generate

    def fake_generate(*args, **kwargs):
        from astra_multi.schemas import ModelResult
        return ModelResult(content="test", usage={"total_tokens": 100})

    gateway_module.generate = fake_generate

    try:
        gateway.call("fake", "planner", [])

        stats = budget.get_stats()
        assert stats["call_count"] == 1
        assert stats["used_tokens"] == 100
    finally:
        gateway_module.generate = original_generate


def test_output_repair_enabled():
    """Output repair should be enabled by default."""
    gateway = ModelGateway()
    assert gateway.config.enable_output_repair is True


def test_output_repair_disabled():
    """Output repair can be disabled."""
    gateway = ModelGateway(config=GatewayConfig(enable_output_repair=False))
    assert gateway.config.enable_output_repair is False


def test_budget_hook_enabled():
    """Budget hook should be enabled by default when provided."""
    budget = BudgetHook(max_calls=10)
    gateway = ModelGateway(budget_hook=budget)
    assert gateway.config.enable_budget_hook is True


def test_budget_hook_disabled():
    """Budget hook can be disabled via config."""
    budget = BudgetHook(max_calls=0)
    gateway = ModelGateway(
        budget_hook=budget, config=GatewayConfig(enable_budget_hook=False)
    )

    import astra_multi.gateway.model_gateway as gateway_module
    original_generate = gateway_module.generate

    def fake_generate(*args, **kwargs):
        from astra_multi.schemas import ModelResult
        return ModelResult(content="test")

    gateway_module.generate = fake_generate

    try:
        # Should succeed even though budget is 0
        gateway.call("fake", "planner", [])
    finally:
        gateway_module.generate = original_generate


def test_attempt_trace_after_call():
    """Attempt trace should be accessible after call."""
    gateway = ModelGateway()

    import astra_multi.gateway.model_gateway as gateway_module
    original_generate = gateway_module.generate

    def fake_generate(*args, **kwargs):
        from astra_multi.schemas import ModelResult
        return ModelResult(content="test", usage={"total_tokens": 100})

    gateway_module.generate = fake_generate

    try:
        gateway.call("fake", "planner", [])

        traces = gateway.get_attempt_traces()
        assert len(traces) == 1
        assert traces[0].attempt_number == 1
        assert traces[0].provider == "fake"
        assert traces[0].error is None
    finally:
        gateway_module.generate = original_generate
