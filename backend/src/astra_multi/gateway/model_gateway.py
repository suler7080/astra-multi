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
    is_estimated: bool = False


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
        self.last_cumulative_usage: dict[str, int | None] | None = None
        self.last_cumulative_cost: float | None = None

    def get_attempt_traces(self) -> list[AttemptTrace]:
        """Get all attempt traces for the gateway session."""
        return self._attempt_traces.copy()

    def clear_traces(self) -> None:
        """Clear all attempt traces."""
        self._attempt_traces.clear()
        self.last_cumulative_usage = None
        self.last_cumulative_cost = None

    def call(
        self,
        provider: str,
        role: str,
        messages: list[dict[str, str]],
        output_schema: type[BaseModel] | str | None = None,
        tool_specs: list[dict[str, Any]] | None = None,
        limits: GenerationLimits | Any | None = None,
        *,
        limits_override: dict[str, Any] | None = None,
        settings: Any = None,
        credentials: Any = None,
    ) -> ModelResult:
        """Execute a model call with retry and budget control."""
        if limits is None:
            limits = GenerationLimits(
                max_retries=self.config.default_max_retries,
                timeout=self.config.default_timeout,
            )
        elif not isinstance(limits, GenerationLimits):
            limits = GenerationLimits.model_validate(limits)

        if limits_override:
            limits_data = limits.model_dump()
            limits_data.update({k: v for k, v in limits_override.items() if v is not None})
            limits = GenerationLimits.model_validate(limits_data)

        # Budget check before initial attempt
        estimated_tokens = sum(len(m.get("content", "")) for m in messages) // 4
        estimated_cost = round((estimated_tokens / 1000.0) * 0.01, 6)
        if self.budget_hook and self.config.enable_budget_hook:
            self.budget_hook.check_reservation(
                estimated_tokens=estimated_tokens,
                estimated_cost_usd=estimated_cost,
            )

        # Execute with retry logic
        last_error: Exception | None = None
        attempt = 0
        max_attempts = limits.max_retries + 1

        cumulative_prompt_tokens = 0
        cumulative_completion_tokens = 0
        cumulative_total_tokens = 0
        cumulative_cost = 0.0
        has_estimated_usage = False

        def _sync_cumulative() -> None:
            if cumulative_total_tokens > 0 or cumulative_prompt_tokens > 0:
                self.last_cumulative_usage = {
                    "prompt_tokens": cumulative_prompt_tokens,
                    "completion_tokens": cumulative_completion_tokens,
                    "total_tokens": cumulative_total_tokens,
                }
            else:
                self.last_cumulative_usage = None
            self.last_cumulative_cost = (
                round(cumulative_cost, 6) if cumulative_cost > 0.0 else 0.0
            )

        def _attach_cumulative(exc: Exception) -> Exception:
            _sync_cumulative()
            setattr(exc, "cumulative_usage", self.last_cumulative_usage)
            setattr(exc, "cumulative_cost_usd", self.last_cumulative_cost)
            return exc

        while attempt < max_attempts:
            if attempt > 0 and self.budget_hook and self.config.enable_budget_hook:
                try:
                    self.budget_hook.check_reservation(
                        estimated_tokens=estimated_tokens,
                        estimated_cost_usd=estimated_cost,
                    )
                except BudgetExceededError as e:
                    raise _attach_cumulative(e)

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
                raw_total = (
                    result.usage.get("total_tokens")
                    if result.usage
                    else None
                )
                raw_prompt = (
                    result.usage.get("prompt_tokens")
                    if result.usage
                    else 0
                )
                raw_comp = (
                    result.usage.get("completion_tokens")
                    if result.usage
                    else 0
                )
                raw_cost = (
                    result.cost_actual_usd
                    if result.cost_actual_usd is not None
                    else (
                        round(((raw_total or 0) / 1000.0) * 0.01, 6)
                        if raw_total
                        else 0.0
                    )
                )

                self._attempt_traces.append(
                    AttemptTrace(
                        attempt_number=attempt,
                        timestamp=time.time(),
                        provider=provider,
                        model_id=result.model_id,
                        latency_seconds=latency,
                        tokens_used=raw_total,
                        is_estimated=False,
                    )
                )

                # Output repair if enabled
                if self.config.enable_output_repair and output_schema is not None:
                    try:
                        result = self._repair_output(result, output_schema, provider)
                    except Exception:
                        # Output repair failed: provider processed the request and billed for it
                        cumulative_total_tokens += (raw_total or 0)
                        cumulative_prompt_tokens += (raw_prompt or 0)
                        cumulative_completion_tokens += (raw_comp or 0)
                        cumulative_cost += raw_cost
                        if self.budget_hook and self.config.enable_budget_hook:
                            self.budget_hook.record_usage(
                                used_tokens=raw_total, used_cost_usd=raw_cost
                            )
                        _sync_cumulative()
                        raise

                # Successful output and validation
                cumulative_total_tokens += (raw_total or 0)
                cumulative_prompt_tokens += (raw_prompt or 0)
                cumulative_completion_tokens += (raw_comp or 0)
                cumulative_cost += raw_cost

                if self.budget_hook and self.config.enable_budget_hook:
                    self.budget_hook.record_usage(
                        used_tokens=raw_total, used_cost_usd=raw_cost
                    )

                _sync_cumulative()
                result.attempts = attempt
                result.cumulative_usage = self.last_cumulative_usage or result.usage
                result.cumulative_cost_usd = (
                    self.last_cumulative_cost
                    if (self.last_cumulative_cost or 0.0) > 0.0
                    else result.cost_actual_usd
                )
                result.is_estimated = has_estimated_usage
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
                raise _attach_cumulative(e)
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
                    raise _attach_cumulative(e)
                last_error = e
                time.sleep(1 * attempt)  # Exponential backoff
            except TimeoutError as e:
                # Distinguish connect timeout vs read timeout
                err_lower = str(e).lower()
                cause_lower = str(getattr(e, "__cause__", "")).lower()
                is_connect = any(
                    term in err_lower or term in cause_lower
                    for term in ("connect", "connection", "resolution")
                )
                if is_connect:
                    timeout_tokens = 0
                    timeout_cost = 0.0
                else:
                    timeout_tokens = estimated_tokens
                    timeout_cost = estimated_cost
                    has_estimated_usage = True

                if timeout_tokens > 0 or timeout_cost > 0:
                    cumulative_total_tokens += timeout_tokens
                    cumulative_prompt_tokens += timeout_tokens
                    cumulative_cost += timeout_cost
                    if self.budget_hook and self.config.enable_budget_hook:
                        self.budget_hook.record_usage(
                            used_tokens=timeout_tokens,
                            used_cost_usd=timeout_cost,
                        )

                self._attempt_traces.append(
                    AttemptTrace(
                        attempt_number=attempt,
                        timestamp=time.time(),
                        provider=provider,
                        error=str(e),
                        tokens_used=timeout_tokens if timeout_tokens > 0 else None,
                        is_estimated=not is_connect,
                    )
                )
                if attempt >= max_attempts:
                    raise _attach_cumulative(e)
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
                    raise _attach_cumulative(e)
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
                    raise _attach_cumulative(e)
                last_error = e
                time.sleep(1 * attempt)

        # All retries exhausted
        _sync_cumulative()
        if last_error:
            raise _attach_cumulative(last_error)
        err = ProviderError("MAX_RETRIES_EXCEEDED", "All retry attempts failed", provider)
        raise _attach_cumulative(err)

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
