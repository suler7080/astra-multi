"""Capability registry for model features and routing."""

from dataclasses import dataclass
from enum import Enum
from typing import Literal


class Capability(str, Enum):
    """Known model capabilities."""
    JSON_MODE = "json_mode"
    TOOL_CALLING = "tool_calling"
    MULTIMODAL = "multimodal"
    STREAMING = "streaming"
    LOW_LATENCY = "low_latency"
    HIGH_TOKEN_LIMIT = "high_token_limit"
    CHEAP = "cheap"


@dataclass
class ModelCapability:
    """Capability metadata for a model."""
    model_id: str
    provider: str
    capabilities: set[Capability]
    max_tokens: int | None = None
    input_cost_per_1k_tokens: float | None = None
    output_cost_per_1k_tokens: float | None = None


class CapabilityRegistry:
    """Registry for model capabilities and role-based routing."""

    def __init__(self) -> None:
        self._models: dict[str, ModelCapability] = {}
        self._role_mapping: dict[str, list[str]] = {}

    def register(self, capability: ModelCapability) -> None:
        """Register a model's capabilities."""
        key = f"{capability.provider}:{capability.model_id}"
        self._models[key] = capability

    def register_role(self, role: str, model_ids: list[str]) -> None:
        """Map a role to a list of preferred models."""
        self._role_mapping[role] = model_ids

    def get_model(self, provider: str, model_id: str) -> ModelCapability | None:
        """Get capability info for a specific model."""
        key = f"{provider}:{model_id}"
        return self._models.get(key)

    def get_role_models(self, role: str) -> list[str]:
        """Get preferred models for a role."""
        return self._role_mapping.get(role, [])

    def has_capability(self, provider: str, model_id: str, capability: Capability) -> bool:
        """Check if a model has a specific capability."""
        model = self.get_model(provider, model_id)
        return model is not None and capability in model.capabilities

    def find_by_capability(self, capability: Capability) -> list[ModelCapability]:
        """Find all models with a specific capability."""
        return [m for m in self._models.values() if capability in m.capabilities]
