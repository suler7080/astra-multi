"""Model gateway for role-based provider routing and capability management."""

from astra_multi.gateway.capabilities import (
    Capability,
    CapabilityRegistry,
    ModelCapability,
)
from astra_multi.gateway.model_gateway import (
    AttemptTrace,
    BudgetExceededError,
    BudgetHook,
    GatewayConfig,
    ModelGateway,
)

__all__ = [
    "Capability",
    "CapabilityRegistry",
    "ModelCapability",
    "ModelGateway",
    "GatewayConfig",
    "BudgetHook",
    "BudgetExceededError",
    "AttemptTrace",
]
