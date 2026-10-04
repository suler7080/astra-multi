# ADR-004 — Model gateway with retry, budget control, and output repair

Status: Accepted for P3, 2026-10-04.

## Decision

Implement a centralized ModelGateway that handles:
- Provider routing based on role configuration
- Transient error retry with exponential backoff
- Budget control via optional BudgetHook
- Output repair for malformed JSON/schema responses
- Capability registry for model feature discovery

The gateway sits between domain logic and provider adapters, ensuring
consistent error handling, usage tracking, and policy enforcement.

## Architecture

### Components

1. **CapabilityRegistry**: Stores model capabilities (JSON mode, tool calling, etc.)
   and role-to-model mappings for intelligent routing.

2. **ModelGateway**: Central entry point for model calls with:
   - Retry logic for transient errors (rate limit, timeout, context overflow)
   - Budget pre-check and post-recording via BudgetHook
   - Output repair for schema validation failures (single attempt)
   - Usage tracking (tokens, cost, latency)

3. **BudgetHook**: Optional budget enforcement:
   - Max total tokens
   - Max total cost in USD
   - Max number of calls
   - Raises BudgetExceededError when limits exceeded

4. **FakeProvider**: Testing utility for deterministic behavior simulation:
   - Configurable failure modes (auth, rate limit, schema errors)
   - Delay simulation
   - Empty/invalid response generation

### Error Classification

- **AuthError**: No retry (permanent)
- **RateLimitError**: Retry with exponential backoff
- **TimeoutError**: Retry with exponential backoff
- **ContextOverflowError**: Retry with reduced context
- **SchemaError**: Single output repair attempt, then fail
- **Other ProviderError**: Retry with exponential backoff

### Output Repair

When output schema validation fails:
1. Attempt to extract JSON from markdown code blocks
2. Parse and validate against schema
3. If repair fails, raise SchemaError with REPAIR_FAILED code

### Budget Control

Budget enforcement is optional but recommended:
- Pre-check reservation before call
- Post-record actual usage after call
- Atomic enforcement prevents overspending
- Reservations not immediately consumed; pending/estimated vs actual

## Consequences

### Positive

- Consistent error handling across all model calls
- Budget protection prevents runaway costs
- Output repair improves robustness for LLM responses
- Capability registry enables intelligent routing
- Fake providers enable deterministic testing

### Negative

- Additional abstraction layer adds complexity
- Output repair may mask real issues if overused
- Budget hook is optional - may be forgotten
- Retry logic may delay failures

### Alternatives

Direct provider calls: Rejected because no consistent error handling,
no budget control, no output repair.

Provider SDK retry only: Rejected because provider SDKs have different
retry strategies and no budget integration.

No output repair: Rejected because LLM responses are often malformed;
repair improves success rate significantly.

## References

- P3.1 requirements in plans/P3_MODELS_AND_WORKFLOW.md
- Provider adapters in src/astra_multi/providers.py
- Gateway implementation in src/astra_multi/gateway/
