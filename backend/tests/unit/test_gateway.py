"""Unit tests for model gateway components."""

import pytest

from astra_multi.gateway.capabilities import Capability, CapabilityRegistry, ModelCapability
from astra_multi.gateway.fake import FakeProvider, FakeProviderConfig
from astra_multi.gateway.model_gateway import (
    BudgetExceededError,
    BudgetHook,
    GatewayConfig,
    ModelGateway,
)
from astra_multi.providers import AuthError, RateLimitError, SchemaError


def test_capability_registry():
    registry = CapabilityRegistry()

    # Register model
    capability = ModelCapability(
        model_id="gpt-4",
        provider="openai",
        capabilities={Capability.JSON_MODE, Capability.TOOL_CALLING},
        max_tokens=8192,
        input_cost_per_1k_tokens=0.03,
        output_cost_per_1k_tokens=0.06,
    )
    registry.register(capability)

    # Retrieve model
    retrieved = registry.get_model("openai", "gpt-4")
    assert retrieved is not None
    assert retrieved.model_id == "gpt-4"
    assert Capability.JSON_MODE in retrieved.capabilities

    # Check capability
    assert registry.has_capability("openai", "gpt-4", Capability.JSON_MODE)
    assert not registry.has_capability("openai", "gpt-4", Capability.MULTIMODAL)

    # Find by capability
    json_models = registry.find_by_capability(Capability.JSON_MODE)
    assert len(json_models) == 1
    assert json_models[0].model_id == "gpt-4"


def test_role_mapping():
    registry = CapabilityRegistry()

    # Register role mapping
    registry.register_role("planner", ["openai:gpt-4", "google:gemini-pro"])
    registry.register_role("reviewer", ["google:gemini-pro"])

    # Get role models
    planner_models = registry.get_role_models("planner")
    assert len(planner_models) == 2
    assert "openai:gpt-4" in planner_models

    reviewer_models = registry.get_role_models("reviewer")
    assert len(reviewer_models) == 1
    assert "google:gemini-pro" in reviewer_models


def test_budget_hook():
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


def test_budget_hook_token_limit():
    hook = BudgetHook(max_total_tokens=100)

    # Should pass
    hook.check_reservation(estimated_tokens=50)
    hook.record_usage(used_tokens=50)

    # Should exceed
    with pytest.raises(BudgetExceededError, match="Max tokens"):
        hook.check_reservation(estimated_tokens=60)


def test_budget_hook_cost_limit():
    hook = BudgetHook(max_total_cost_usd=0.5)

    # Should pass
    hook.check_reservation(estimated_cost_usd=0.3)
    hook.record_usage(used_cost_usd=0.3)

    # Should exceed
    with pytest.raises(BudgetExceededError, match="Max cost"):
        hook.check_reservation(estimated_cost_usd=0.3)


def test_fake_provider():
    provider = FakeProvider()

    # Normal call
    result = provider.generate("planner", [{"role": "user", "content": "test"}])
    assert result.content == "Fake response content"
    assert result.provider == "fake"
    assert result.usage is not None
    assert result.usage["total_tokens"] == 150


def test_fake_provider_failure():
    config = FakeProviderConfig(should_fail=True, error_type="AUTH")
    provider = FakeProvider(config)

    with pytest.raises(AuthError):
        provider.generate("planner", [{"role": "user", "content": "test"}])


def test_fake_provider_schema_error():
    config = FakeProviderConfig(should_fail=True, error_type="SCHEMA")
    provider = FakeProvider(config)

    with pytest.raises(SchemaError):
        provider.generate("planner", [{"role": "user", "content": "test"}])


def test_fake_provider_empty_response():
    config = FakeProviderConfig(empty_response=True)
    provider = FakeProvider(config)

    with pytest.raises(SchemaError, match="EMPTY_RESPONSE"):
        provider.generate("planner", [{"role": "user", "content": "test"}])


def test_fake_provider_rate_limit():
    config = FakeProviderConfig(rate_limit_after=1)
    provider = FakeProvider(config)

    # First call should pass
    provider.generate("planner", [{"role": "user", "content": "test"}])

    # Second call should rate limit
    with pytest.raises(RateLimitError):
        provider.generate("planner", [{"role": "user", "content": "test"}])


def test_fake_provider_with_schema():
    provider = FakeProvider()

    result = provider.generate(
        "planner",
        [{"role": "user", "content": "test"}],
        output_schema=dict,  # Just for testing
    )
    assert isinstance(result.content, dict)
    assert "findings" in result.content


def test_gateway_config():
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


def test_gateway_initialization():
    gateway = ModelGateway()
    assert gateway.config.default_max_retries == 2
    assert gateway.config.default_timeout == 120
    assert gateway.config.enable_output_repair
    assert gateway.budget_hook is None

    custom_config = GatewayConfig(default_max_retries=5)
    gateway = ModelGateway(config=custom_config)
    assert gateway.config.default_max_retries == 5


def test_gateway_with_budget_hook():
    budget = BudgetHook(max_calls=1)
    gateway = ModelGateway(budget_hook=budget)

    assert gateway.budget_hook is budget
    assert gateway.config.enable_budget_hook
