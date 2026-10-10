"""Unit and integration tests for F-06:
Gateway retry budget checking, cumulative usage accounting, and budget ledger integrity.
"""

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from astra_multi.context.bundle import ContextBuilder
from astra_multi.domain.fixtures import sample_state
from astra_multi.gateway.model_gateway import (
    BudgetExceededError,
    BudgetHook,
    GatewayConfig,
    ModelGateway,
)
from astra_multi.orchestration.budget import BudgetService
from astra_multi.orchestration.controller import WorkflowController
from astra_multi.orchestration.graph import (
    WorkflowContext,
    create_workflow_graph,
)
from astra_multi.persistence.sqlite import SQLiteStore
from astra_multi.providers import (
    ContextOverflowError,
    GenerationLimits,
    RateLimitError,
    TimeoutError,
)
from astra_multi.schemas import ModelResult


class PlanSchema(BaseModel):
    approach: str


# ============================================================================
# KỊCH BẢN 1: Retry sau lỗi tốn tiền (Read Timeout)
# ============================================================================
def test_scenario_1_retry_after_costly_failure_records_all_tokens_and_calls() -> None:
    """Kịch bản 1: Lần 1 read timeout tốn 800 tokens, lần 2 thành công tốn 800 tokens.
    Mong muốn:
    - Sổ cái/BudgetHook ghi nhận đầy đủ cả 2 lần: 1600 tokens.
    - Số call ghi nhận khớp: 2 calls.
    - res.usage bảo lưu kết quả lần cuối: 800 tokens.
    - res.cumulative_usage phản ánh toàn bộ 1600 tokens.
    """
    call_log: list[dict[str, Any]] = []

    def mock_adapter(provider: str, role: str, messages: list[dict[str, Any]], output_schema: Any = None, **kwargs: Any) -> ModelResult:
        attempt_num = len(call_log) + 1
        call_log.append({"attempt": attempt_num, "tokens": 800, "cost": 0.008})
        if attempt_num == 1:
            raise TimeoutError("TIMEOUT", "Read timed out waiting for upstream LLM", provider)
        return ModelResult(
            content="Plan draft content",
            model_id="mock-llm",
            provider="mock",
            usage={"total_tokens": 800, "prompt_tokens": 700, "completion_tokens": 100},
            cost_actual_usd=0.008,
        )

    budget_hook = BudgetHook(max_total_tokens=3000, max_calls=5)
    gateway = ModelGateway(
        config=GatewayConfig(enable_budget_hook=True, enable_output_repair=False),
        budget_hook=budget_hook,
        provider_adapter=mock_adapter,
    )

    result = gateway.call(
        provider="mock",
        role="planner",
        messages=[{"role": "user", "content": "x" * 3200}],  # 3200 chars // 4 = 800 tokens prompt
        limits=GenerationLimits(max_retries=2, timeout=5.0),
    )

    stats = budget_hook.get_stats()
    # 1. Tổng calls thực tế gọi tới adapter là 2
    assert len(call_log) == 2
    # 2. Số calls ghi nhận trong budget khớp với số request thực tế
    assert stats["call_count"] == 2
    # 3. Token ghi nhận trong budget hook == tổng token thực tế của provider (1600)
    assert stats["used_tokens"] == 1600
    # 4. res.usage giữ nguyên giá trị lần gọi thành công cuối (800)
    assert result.usage is not None and result.usage["total_tokens"] == 800
    # 5. res.cumulative_usage phản ánh tổng cộng (1600)
    assert result.cumulative_usage is not None
    assert result.cumulative_usage["total_tokens"] == 1600


# ============================================================================
# KỊCH BẢN 2: Tất cả các lần thử đều lỗi
# ============================================================================
def test_scenario_2_all_retries_fail_preserves_incurred_costs_and_zero_active_reservations():
    """Kịch bản 2: Khi tất cả các lần thử đều lỗi (Read Timeout).
    Mong muốn:
    - Chi phí đã biết/ước tính của các lần gọi được ghi nhận vào BudgetService (used_tokens > 0).
    - active_reservations == 0 (không rò rỉ reservation slot).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_scenario_2.db"
        store = SQLiteStore(db_path)
        try:
            state = sample_state()
            store.create(state.task, state.run, state.snapshot)
            lease = store.acquire(state.run.id, owner="test-worker", ttl=60)

            budget_service = BudgetService(
                token_limit=20000,
                cost_limit=0.50,
                repository=store,
                lease=lease,
            )

            call_count = 0

            def always_fail_adapter(provider, role, messages, **kwargs):
                nonlocal call_count
                call_count += 1
                raise TimeoutError("TIMEOUT", "Read timed out waiting for upstream LLM", provider)

            gateway = ModelGateway(
                config=GatewayConfig(enable_output_repair=False),
                provider_adapter=always_fail_adapter,
            )

            controller = WorkflowController(store, lease, actor="test")
            context_builder = ContextBuilder(store.artifacts)
            wf_ctx = WorkflowContext(
                controller=controller,
                gateway=gateway,
                context_builder=context_builder,
                budget_service=budget_service,
            )

            app = create_workflow_graph(wf_ctx).compile()

            with pytest.raises(TimeoutError):
                app.invoke({"run_id": state.run.id, "round": 0, "max_rounds": 1, "events": []})

            summary = budget_service.get_summary()
            assert call_count > 0
            # Chi phí đã biết được ghi nhận, KHÔNG bị release về 0!
            assert summary["used_tokens"] > 0
            assert summary["used_cost"] > 0.0
            # active reservations phải giải phóng sạch sẽ (== 0)
            assert summary["active_reservations"] == 0
        finally:
            store.close()


# ============================================================================
# KỊCH BẢN 3: Trần 1000, ước tính 600, lần 1 JSON hỏng tốn 700
# ============================================================================
def test_scenario_3_malformed_json_exhausts_budget_blocks_retry_and_reports_exceeded():
    """Kịch bản 3: Trần 1000, ước tính 600. Lần 1 JSON hỏng tốn 700 tokens.
    Mong muốn:
    - Phần còn lại (300) nhỏ hơn ước tính (600) -> KHÔNG retry!
    - Tổng thực tế tại provider <= trần (chỉ đúng 1 lần gọi = 700 tokens).
    - Ghi nhận trong budget == thực tế (700 tokens).
    - Gateway báo vượt ngân sách theo đúng ngoại lệ BudgetExceededError.
    """
    call_history: list[dict] = []

    def malformed_first_adapter(provider, role, messages, output_schema=None, **kwargs):
        attempt_idx = len(call_history) + 1
        call_history.append({"attempt": attempt_idx, "tokens": 700, "cost": 0.007})
        return ModelResult(
            content="INVALID_JSON_{{broken",
            model_id="mock-llm",
            provider="mock",
            usage={"total_tokens": 700, "prompt_tokens": 600, "completion_tokens": 100},
            cost_actual_usd=0.007,
        )

    # Trần ngân sách: 1000 tokens
    token_ceiling = 1000
    budget_hook = BudgetHook(max_total_tokens=token_ceiling)
    gateway = ModelGateway(
        config=GatewayConfig(enable_output_repair=True, enable_budget_hook=True),
        budget_hook=budget_hook,
        provider_adapter=malformed_first_adapter,
    )

    # Prompt dài ~600 tokens ước tính
    messages = [{"role": "user", "content": "plan " * 600}]

    with pytest.raises(BudgetExceededError, match="Max tokens 1000 would be exceeded"):
        gateway.call(
            provider="mock",
            role="planner",
            messages=messages,
            output_schema=PlanSchema,
            limits=GenerationLimits(max_retries=1, timeout=5.0),
        )

    # 1. KHÔNG retry: số lần gọi tới provider chỉ đúng 1 lần
    assert len(call_history) == 1
    # 2. Tổng thực tế <= trần (700 <= 1000)
    real_tokens = sum(c["tokens"] for c in call_history)
    assert real_tokens <= token_ceiling
    assert real_tokens == 700
    # 3. Ghi nhận trong budget == thực tế (700)
    stats = budget_hook.get_stats()
    assert stats["used_tokens"] == 700
    assert stats["used_cost_usd"] == 0.007


# ============================================================================
# BỔ SUNG: 429 và Context Overflow không làm tăng chi phí
# ============================================================================
def test_rate_limit_and_context_overflow_do_not_charge_budget():
    """Lỗi 429 (RateLimitError) và context overflow (ContextOverflowError) không làm tăng chi phí."""
    calls_made = 0

    def rate_limit_then_overflow_adapter(provider, role, messages, **kwargs):
        nonlocal calls_made
        calls_made += 1
        if calls_made == 1:
            raise RateLimitError("RATE_LIMIT", "429 Too Many Requests", provider)
        elif calls_made == 2:
            raise ContextOverflowError("CONTEXT_OVERFLOW", "Context window exceeded", provider)
        return ModelResult(
            content="success after transient edge errors",
            usage={"total_tokens": 300, "prompt_tokens": 250, "completion_tokens": 50},
            cost_actual_usd=0.003,
        )

    budget_hook = BudgetHook(max_total_tokens=2000)
    gateway = ModelGateway(
        config=GatewayConfig(enable_budget_hook=True),
        budget_hook=budget_hook,
        provider_adapter=rate_limit_then_overflow_adapter,
    )

    result = gateway.call(
        provider="mock",
        role="planner",
        messages=[{"role": "user", "content": "test"}],
        limits=GenerationLimits(max_retries=3),
    )

    stats = budget_hook.get_stats()
    # Attempt 1 (429) và Attempt 2 (Overflow) đều không tốn token
    # Chỉ attempt 3 thành công mới tính 300 tokens
    assert calls_made == 3
    assert stats["used_tokens"] == 300
    assert stats["used_cost_usd"] == 0.003
    assert result.usage["total_tokens"] == 300
    assert getattr(result, "cumulative_usage", None) is not None
    assert result.cumulative_usage["total_tokens"] == 300


# ============================================================================
# BỔ SUNG: Retry hợp lệ khi phần còn lại ĐỦ vẫn thành công và cộng dồn đúng
# ============================================================================
def test_valid_retry_when_budget_sufficient_succeeds_and_accumulates_correctly():
    """Retry hợp lệ khi phần còn lại đủ ngân sách:
    Trần 3000 tokens. Lần 1 JSON hỏng tốn 700 tokens.
    Phần còn lại (2300) > ước tính 600 -> Được phép retry -> Thành công lần 2 tốn 800 tokens.
    Tổng cộng dồn = 1500 tokens. res.usage == 800.
    """
    call_log: list[int] = []

    def retry_valid_adapter(provider, role, messages, output_schema=None, **kwargs):
        idx = len(call_log) + 1
        call_log.append(idx)
        if idx == 1:
            return ModelResult(
                content="BROKEN_JSON_NOT_VALID",
                usage={"total_tokens": 700, "prompt_tokens": 600, "completion_tokens": 100},
                cost_actual_usd=0.007,
            )
        return ModelResult(
            content=json.dumps({"approach": "Robust verified architecture"}),
            usage={"total_tokens": 800, "prompt_tokens": 650, "completion_tokens": 150},
            cost_actual_usd=0.008,
        )

    budget_hook = BudgetHook(max_total_tokens=3000)
    gateway = ModelGateway(
        config=GatewayConfig(enable_output_repair=True, enable_budget_hook=True),
        budget_hook=budget_hook,
        provider_adapter=retry_valid_adapter,
    )

    res = gateway.call(
        provider="mock",
        role="planner",
        messages=[{"role": "user", "content": "plan " * 400}],
        output_schema=PlanSchema,
        limits=GenerationLimits(max_retries=2),
    )

    assert len(call_log) == 2
    stats = budget_hook.get_stats()
    assert stats["call_count"] == 2
    assert stats["used_tokens"] == 1500
    assert stats["used_cost_usd"] == pytest.approx(0.015, rel=1e-4)
    assert res.usage["total_tokens"] == 800
    assert getattr(res, "cumulative_usage", None) is not None
    assert res.cumulative_usage["total_tokens"] == 1500
    assert res.cumulative_cost_usd == pytest.approx(0.015, rel=1e-4)
