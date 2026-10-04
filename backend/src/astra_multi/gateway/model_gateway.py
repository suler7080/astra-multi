"""Model gateway with retry, budget control, and output repair."""

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, Field

from astra_multi.providers import (
    AuthError,
    ContextOverflowError,
    GenerationLimits,
    ProviderError,
    RateLimitError,
    SchemaError,
    TimeoutError,
    generate,
)
from astra_multi.schemas import ModelResult


@dataclass
class AttemptTrace:
    """Trace information for a single attempt."""
    attempt_number: int
    timestamp: float
    provider: str
    model_id: str | None = None
    error: str | None = None
    latency_seconds: float | None = None
    tokens_used: int | None = None


@dataclass
class GatewayConfig:
    """Configuration for model gateway."""
    default_max_retries: int = 2
    default_timeout: float = 120
    enable_output_repair: bool = True
    enable_budget_hook: bool = True


class BudgetExceededError(Exception):
    """Raised when budget limit is exceeded."""
    pass


class BudgetHook:
    """Hook for budget control before model calls."""

    def __init__(
        self,
        max_total_tokens: int | None = None,
        max_total_cost_usd: float | None = None,
        max_calls: int | None = None,
    ) -> None:
        self.max_total_tokens = max_total_tokens
        self.max_total_cost_usd = max_total_cost_usd
        self.max_calls = max_calls
        self._used_tokens = 0
        self._used_cost_usd = 0.0
        self._call_count = 0

    def check_reservation(
        self,
        estimated_tokens: int | None = None,
        estimated_cost_usd: float | None = None,
    ) -> None:
        """Check if budget allows a new call."""
        if self.max_calls is not None and self._call_count >= self.max_calls:
            raise BudgetExceededError(f"Max calls {self.max_calls} exceeded")
        if (
            self.max_total_tokens is not None
            and estimated_tokens is not None
            and self._used_tokens + estimated_tokens > self.max_total_tokens
        ):
            raise BudgetExceededError(
                f"Max tokens {self.max_total_tokens} would be exceeded"
            )
        if (
            self.max_total_cost_usd is not None
            and estimated_cost_usd is not None
            and self._used_cost_usd + estimated_cost_usd > self.max_total_cost_usd
        ):
            raise BudgetExceededError(
                f"Max cost ${self.max_total_cost_usd} would be exceeded"
            )

    def record_usage(
        self,
        used_tokens: int | None = None,
        used_cost_usd: float | None = None,
    ) -> None:
        """Record actual usage after a call."""
        if used_tokens is not None:
            self._used_tokens += used_tokens
        if used_cost_usd is not None:
            self._used_cost_usd += used_cost_usd
        self._call_count += 1

    def get_stats(self) -> dict[str, Any]:
        """Get current budget statistics."""
        return {
            "used_tokens": self._used_tokens,
            "used_cost_usd": self._used_cost_usd,
            "call_count": self._call_count,
        }


class ModelGateway:
    """Gateway for model calls with retry, budget control, and output repair."""

    def __init__(
        self,
        config: GatewayConfig | None = None,
        budget_hook: BudgetHook | None = None,
        provider_adapter: Callable[..., ModelResult] | None = None,
    ) -> None:
        self.config = config or GatewayConfig()
        self.budget_hook = budget_hook
        self.provider_adapter = provider_adapter
        self._attempt_traces: list[AttemptTrace] = []

    def get_attempt_traces(self) -> list[AttemptTrace]:
        """Get all attempt traces for the gateway session."""
        return self._attempt_traces.copy()

    def clear_traces(self) -> None:
        """Clear all attempt traces."""
        self._attempt_traces.clear()

    def call(
        self,
        provider: str,
        role: str,
        messages: list[dict[str, str]],
        output_schema: type[BaseModel] | str | None = None,
        tool_specs: list[dict[str, Any]] | None = None,
        limits: GenerationLimits | None = None,
        *,
        settings: Any = None,
        credentials: Any = None,
    ) -> ModelResult:
        """Execute a model call with retry and budget control."""
        if limits is None:
            limits = GenerationLimits(
                max_retries=self.config.default_max_retries,
                timeout=self.config.default_timeout,
            )

        # Budget check
        if self.budget_hook and self.config.enable_budget_hook:
            # Estimate tokens from message length (rough estimate)
            estimated_tokens = sum(len(m.get("content", "")) for m in messages) // 4
            self.budget_hook.check_reservation(estimated_tokens=estimated_tokens)

        # Execute with retry logic
        last_error: Exception | None = None
        attempt = 0
        max_attempts = limits.max_retries + 1

        while attempt < max_attempts:
            attempt += 1
            attempt_start = time.perf_counter()
            try:
                if self.provider_adapter is not None:
                    result = self.provider_adapter(
                        provider=provider,
                        role=role,
                        messages=messages,
                        output_schema=output_schema,
                        tool_specs=tool_specs,
                        limits=limits,
                        settings=settings,
                        credentials=credentials,
                    )
                else:
                    result = generate(
                        provider=provider,
                        role=role,
                        messages=messages,
                        output_schema=output_schema,
                        tool_specs=tool_specs,
                        limits=limits,
                        settings=settings,
                        credentials=credentials,
                    )

                # Record successful attempt
                latency = time.perf_counter() - attempt_start
                self._attempt_traces.append(
                    AttemptTrace(
                        attempt_number=attempt,
                        timestamp=time.time(),
                        provider=provider,
                        model_id=result.model_id,
                        latency_seconds=latency,
                        tokens_used=(
                            result.usage.get("total_tokens")
                            if result.usage
                            else None
                        ),
                    )
                )

                # Output repair if enabled
                if self.config.enable_output_repair and output_schema is not None:
                    result = self._repair_output(result, output_schema, provider)

                # Record budget usage
                if self.budget_hook and self.config.enable_budget_hook:
                    total_tokens = (
                        result.usage.get("total_tokens")
                        if result.usage
                        else None
                    )
                    cost = result.cost_actual_usd
                    self.budget_hook.record_usage(
                        used_tokens=total_tokens, used_cost_usd=cost
                    )

                result.attempts = attempt
                return result

            except AuthError as e:
                # Auth errors should not be retried
                self._attempt_traces.append(
                    AttemptTrace(
                        attempt_number=attempt,
                        timestamp=time.time(),
                        provider=provider,
                        error=str(e),
                    )
                )
                raise
            except RateLimitError as e:
                # Transient error - retry if attempts remain
                self._attempt_traces.append(
                    AttemptTrace(
                        attempt_number=attempt,
                        timestamp=time.time(),
                        provider=provider,
                        error=str(e),
                    )
                )
                if attempt >= max_attempts:
                    raise
                last_error = e
                time.sleep(1 * attempt)  # Exponential backoff
            except TimeoutError as e:
                # Transient error - retry if attempts remain
                self._attempt_traces.append(
                    AttemptTrace(
                        attempt_number=attempt,
                        timestamp=time.time(),
                        provider=provider,
                        error=str(e),
                    )
                )
                if attempt >= max_attempts:
                    raise
                last_error = e
                time.sleep(1 * attempt)
            except ContextOverflowError as e:
                # Transient error - retry if attempts remain
                self._attempt_traces.append(
                    AttemptTrace(
                        attempt_number=attempt,
                        timestamp=time.time(),
                        provider=provider,
                        error=str(e),
                    )
                )
                if attempt >= max_attempts:
                    raise
                last_error = e
                # Reduce context size on retry
                if len(messages) > 1:
                    messages = messages[-len(messages) // 2 :]
            except ProviderError as e:
                # Other provider errors - retry if attempts remain
                self._attempt_traces.append(
                    AttemptTrace(
                        attempt_number=attempt,
                        timestamp=time.time(),
                        provider=provider,
                        error=str(e),
                    )
                )
                if attempt >= max_attempts:
                    raise
                last_error = e
                time.sleep(1 * attempt)

        # All retries exhausted
        if last_error:
            raise last_error
        raise ProviderError("MAX_RETRIES_EXCEEDED", "All retry attempts failed", provider)

    def _repair_output(
        self,
        result: ModelResult,
        output_schema: type[BaseModel] | str | None,
        provider: str,
    ) -> ModelResult:
        """Attempt to repair malformed output once."""
        try:
            # If already valid, return as-is
            if output_schema is None:
                return result
            if isinstance(output_schema, type):
                output_schema.model_validate(result.content)
            return result
        except Exception:
            # Try to repair - this is a simple implementation
            # In production, might use LLM-based repair
            import json

            try:
                content_str = str(result.content)
                # Try to extract JSON from markdown code blocks
                if "```json" in content_str:
                    content_str = content_str.split("```json")[1].split("```")[0].strip()
                elif "```" in content_str:
                    content_str = content_str.split("```")[1].split("```")[0].strip()

                parsed = json.loads(content_str)
                # Validate against schema
                if isinstance(output_schema, type):
                    parsed = output_schema.model_validate(parsed).model_dump(
                        mode="json"
                    )

                # Return repaired result
                return ModelResult(
                    content=parsed,
                    usage=result.usage,
                    model_id=result.model_id,
                    attempts=result.attempts,
                    provider=result.provider,
                    latency_seconds=result.latency_seconds,
                    prompt_version=result.prompt_version,
                    schema_version=result.schema_version,
                    cost_estimate_usd=result.cost_estimate_usd,
                    cost_actual_usd=result.cost_actual_usd,
                )
            except Exception:
                # Repair failed, return original error
                raise SchemaError(
                    "REPAIR_FAILED",
                    "Output repair failed - original schema error persists",
                    provider,
                )
