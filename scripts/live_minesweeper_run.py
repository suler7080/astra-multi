#!/usr/bin/env python3
"""Run Minesweeper fixture with live LLM and hard budget cap.

P5.1 requirements:
1. Verify ASTRA_LIVE_LLM=1 and provider API key availability.
   If missing, print clear instructions and exit without running.
2. Hard cost cap (default: 1.00 USD) enforced via BudgetService.
3. Executes Minesweeper fixture across up to 3 independent runs.
4. Records final status, rounds, blocker resolutions, schema conformance,
   and token/cost actuals vs reservations.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Ensure backend/src is on sys.path
repo_root = Path(__file__).resolve().parent.parent
backend_src = repo_root / "backend" / "src"
if str(backend_src) not in sys.path:
    sys.path.insert(0, str(backend_src))

from astra_multi.credentials import OSCredentialStore
from astra_multi.domain.models import (
    IssueSeverity,
    IssueStatus,
    Requirement,
    RunPhase,
    RunStatus,
    TaskSpec,
)
from astra_multi.exports.finalization import FinalizationService, SemanticReviewAssessment
from astra_multi.gateway.model_gateway import GatewayConfig, ModelGateway
from astra_multi.orchestration.budget import BudgetExhaustedError, BudgetService
from astra_multi.orchestration.controller import WorkflowController
from astra_multi.orchestration.graph import (
    ContextBuilder,
    WorkflowContext,
    create_workflow_graph,
)
from astra_multi.persistence.artifacts import FileArtifactStore
from astra_multi.persistence.sqlite import SQLiteStore
from astra_multi.provider_config import ProviderManager, ProviderSettingsRepository
from astra_multi.providers import AuthError, ProviderError, generate


def check_prerequisites(provider_name: str | None = None) -> tuple[bool, str, str | None]:
    """Verify ASTRA_LIVE_LLM=1 and that an active API key exists for the target provider.

    Returns:
        (ready: bool, message: str, resolved_provider: str | None)
    """
    live_env = os.environ.get("ASTRA_LIVE_LLM", "").strip()
    if live_env != "1":
        instructions = (
            "======================================================================\n"
            "THÔNG BÁO: CHƯA KÍCH HOẠT CHẾ ĐỘ LIVE LLM (ASTRA_LIVE_LLM=1)\n"
            "======================================================================\n"
            "Theo quy tắc an toàn ngân sách P5, script chỉ được gọi LLM thật khi:\n"
            "1. Biến môi trường ASTRA_LIVE_LLM được đặt bằng 1:\n"
            "   - Windows PowerShell: $env:ASTRA_LIVE_LLM=\"1\"\n"
            "   - Linux/macOS:        export ASTRA_LIVE_LLM=1\n"
            "2. Có ít nhất một API key hợp lệ được cấu hình qua biến môi trường hoặc OS Keyring:\n"
            "   - OpenAI:   $env:OPENAI_API_KEY=\"sk-...\"\n"
            "   - Google:   $env:GOOGLE_API_KEY=\"AIza...\"\n"
            "   - xKiro:    $env:XKIRO_API_KEY=\"sk-...\" (provider=xkiro)\n"
            "======================================================================"
        )
        return False, instructions, None

    settings_repo = ProviderSettingsRepository()
    credential_store = OSCredentialStore()
    manager = ProviderManager(settings_repo, credential_store)
    settings = settings_repo.load()

    target_provider = provider_name or os.environ.get("ASTRA_MULTI_PROVIDER")
    candidate_profiles = []

    if target_provider:
        try:
            candidate_profiles.append(settings.profile(target_provider))
        except Exception:
            pass
    else:
        # Check all available effective profiles
        candidate_profiles = settings.effective_profiles()

    for profile in candidate_profiles:
        try:
            key = manager.resolve_key(profile)
            if key and len(key.strip()) > 0:
                return True, f"Found valid key for provider '{profile.name}' (model: {profile.model})", profile.name
        except Exception:
            continue

    # No key found
    instructions = (
        "======================================================================\n"
        "THÔNG BÁO: THIẾU API KEY CHO LIVE LLM\n"
        "======================================================================\n"
        "ASTRA_LIVE_LLM=1 đã được bật, nhưng không tìm thấy API key hợp lệ nào.\n"
        "Vui lòng thiết lập một trong các API key sau:\n"
        "1. OpenAI:\n"
        "   $env:OPENAI_API_KEY=\"sk-...\"\n"
        "   $env:ASTRA_MULTI_PROVIDER=\"openai\"\n"
        "2. Google Gemini:\n"
        "   $env:GOOGLE_API_KEY=\"AIza...\"\n"
        "   $env:ASTRA_MULTI_PROVIDER=\"google\"\n"
        "3. xKiro API:\n"
        "   $env:XKIRO_API_KEY=\"sk-...\"\n"
        "   $env:ASTRA_MULTI_PROVIDER=\"xkiro\"\n"
        "Hoặc lưu key vào Windows Credential Manager thông qua CLI:\n"
        "   astra-multi provider configure <profile-name>\n"
        "======================================================================"
    )
    return False, instructions, None


def run_single_minesweeper(
    run_index: int,
    provider: str,
    cost_limit_usd: float = 1.00,
    max_rounds: int = 2,
) -> dict[str, Any]:
    """Execute one independent Minesweeper run with the live provider and budget cap."""
    print(f"\n--- [Run {run_index}] Khởi động với provider '{provider}', trần ngân sách: ${cost_limit_usd:.2f} USD ---")

    schema_errors: list[dict[str, Any]] = []

    # Wrapper to observe schema errors without breaking gateway contract
    def observed_provider_adapter(
        provider: str,
        role: str,
        messages: list[dict[str, str]],
        output_schema: Any = None,
        **kwargs: Any,
    ) -> Any:
        try:
            return generate(
                provider=provider,
                role=role,
                messages=messages,
                output_schema=output_schema,
                **kwargs,
            )
        except ProviderError as pe:
            if "INVALID_SCHEMA" in str(pe) or "EMPTY_RESPONSE" in str(pe):
                schema_errors.append({
                    "role": role,
                    "error": str(pe),
                    "timestamp": time.time(),
                })
            raise

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / f"live_minesweeper_run_{run_index}.db"
        art_path = Path(tmpdir) / "artifacts"
        art_path.mkdir(parents=True, exist_ok=True)

        with SQLiteStore(db_path) as store:
            art_store = FileArtifactStore(art_path)

            task_spec = TaskSpec(
                id=f"TASK-MINESWEEPER-{run_index}",
                title="Minesweeper Board Logic with Seedable PRNG",
                mode="greenfield",
                repo_context=False,
                requirements=[
                    Requirement(
                        id="REQ-001",
                        text="Grid allocation and 9x9 board representation with cell states",
                        acceptance="Valid board structure created",
                    ),
                    Requirement(
                        id="REQ-002",
                        text="Deterministic mine placement supporting optional integer seed for replayability",
                        acceptance="Same seed produces identical mine coordinates",
                    ),
                ],
            )

            from astra_multi.domain.models import Run, Snapshot, utc_now
            initial_run = Run(
                id=f"RUN-LIVE-MS-{run_index}-{int(time.time())}",
                task_id=task_spec.id,
                phase=RunPhase.INTAKE,
                status=RunStatus.RUNNING,
                created_at=utc_now(),
            )
            snapshot = Snapshot(
                id=f"SNAP-{run_index}",
                repo_sha=None,
                tree_hash="0" * 64,
                created_at=utc_now(),
            )

            store.create(task_spec, initial_run, snapshot)
            lease = store.acquire(initial_run.id, owner=f"live-worker-{run_index}", ttl=300)

            controller = WorkflowController(store, lease)
            budget_service = BudgetService(
                cost_limit=cost_limit_usd,
                repository=store,
                lease=lease,
            )
            gateway = ModelGateway(
                config=GatewayConfig(enable_output_repair=True),
                provider_adapter=observed_provider_adapter,
            )
            context_builder = ContextBuilder(art_store)

            wf_ctx = WorkflowContext(
                controller=controller,
                gateway=gateway,
                context_builder=context_builder,
                budget_service=budget_service,
                provider=provider,
            )

            graph = create_workflow_graph(wf_ctx)
            app = graph.compile()

            initial_state = {
                "run_id": initial_run.id,
                "round": 0,
                "max_rounds": max_rounds,
                "events": [],
            }

            start_time = time.perf_counter()
            error_reason = None
            final_output = None

            try:
                final_output = app.invoke(initial_state)
            except BudgetExhaustedError as be:
                error_reason = f"BUDGET_EXHAUSTED: {be}"
                print(f"[Run {run_index}] Cảnh báo trần ngân sách: {be}")
            except Exception as e:
                error_reason = f"EXECUTION_ERROR: {e}"
                print(f"[Run {run_index}] Lỗi thực thi: {e}")

            elapsed = time.perf_counter() - start_time
            final_state = store.load(initial_run.id)

            # Evaluate final blocking issues
            blocking_issues = [i for i in final_state.issues if i.severity == IssueSeverity.BLOCKING]
            resolved_blockers = [i for i in blocking_issues if i.status == IssueStatus.RESOLVED]
            unresolved_blockers = [i for i in blocking_issues if i.status != IssueStatus.RESOLVED]

            # Collect model calls stats
            model_calls = final_state.model_calls
            total_tokens = sum((c.usage.get("total_tokens") or 0) for c in model_calls if c.usage)
            total_cost_usd = budget_service.total_used_cost

            # Check P4 finalization if gate passed
            can_finalize = False
            if final_output and final_output.get("gate_passed"):
                finalization_svc = FinalizationService()
                decision = finalization_svc.evaluate(
                    final_state,
                    semantic_review=SemanticReviewAssessment(
                        passed=True,
                        reviewed_plan_revision=final_state.plan.revision if final_state.plan else 1,
                        feedback="Live run evaluated",
                        concerns=[],
                    ),
                )
                can_finalize = decision.can_finalize

            result = {
                "run_index": run_index,
                "run_id": initial_run.id,
                "provider": provider,
                "status": final_state.run.status.value,
                "rounds": final_output.get("round", 0) if final_output else 0,
                "gate_passed": final_output.get("gate_passed", False) if final_output else False,
                "can_finalize": can_finalize,
                "blocking_total": len(blocking_issues),
                "blocking_resolved": len(resolved_blockers),
                "unresolved_blocker_ids": [i.id for i in unresolved_blockers],
                "schema_errors": schema_errors,
                "total_tokens": total_tokens,
                "total_cost_usd": total_cost_usd,
                "model_calls_count": len(model_calls),
                "elapsed_seconds": elapsed,
                "error_reason": error_reason,
            }

            print(f"[Run {run_index}] Hoàn thành: Status={result['status']}, Rounds={result['rounds']}, "
                  f"Blockers={result['blocking_resolved']}/{result['blocking_total']} resolved, "
                  f"Tokens={result['total_tokens']}, Cost=${result['total_cost_usd']:.4f}, "
                  f"SchemaErrors={len(schema_errors)}, Elapsed={elapsed:.1f}s")

            return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Live Minesweeper Run with Budget Cap")
    parser.add_argument("--runs", type=int, default=3, help="Số lần chạy độc lập tối đa (mặc định: 3)")
    parser.add_argument("--provider", type=str, default=None, help="Tên provider (openai, google, xkiro,...)")
    parser.add_argument("--budget-cap", type=float, default=1.00, help="Trần ngân sách cứng USD (mặc định: 1.00)")
    parser.add_argument("--markdown-out", type=str, default="LIVE_RUN.md", help="Đường dẫn file ghi kết quả markdown")
    args = parser.parse_args()

    # Step 1: Check prerequisites
    ready, message, active_provider = check_prerequisites(args.provider)
    print(message)
    if not ready:
        return 1

    provider = active_provider or "openai"
    max_runs = min(max(args.runs, 1), 3)

    print(f"\nBắt đầu thực hiện {max_runs} lần chạy độc lập Minesweeper với model thật...")
    run_results: list[dict[str, Any]] = []

    for i in range(1, max_runs + 1):
        try:
            res = run_single_minesweeper(
                run_index=i,
                provider=provider,
                cost_limit_usd=args.budget_cap,
            )
            run_results.append(res)
        except Exception as e:
            print(f"Lỗi nghiêm trọng ở Run {i}: {e}")
            run_results.append({
                "run_index": i,
                "status": "FAILED",
                "rounds": 0,
                "blocking_total": 0,
                "blocking_resolved": 0,
                "schema_errors": [{"error": str(e)}],
                "total_tokens": 0,
                "total_cost_usd": 0.0,
                "elapsed_seconds": 0.0,
                "error_reason": str(e),
            })

    # Step 2 & 3: Generate LIVE_RUN.md
    md_lines = [
        "# Báo Cáo Chạy Kiểm Thử Với Mô Hình Thật (LIVE_RUN.md)",
        "",
        f"**Thời điểm thực thi:** {time.strftime('%Y-%m-%d %H:%M:%S')}  ",
        f"**Provider:** `{provider}`  ",
        f"**Trần ngân sách tối đa:** `${args.budget_cap:.2f} USD` (Enforced via `BudgetService`)  ",
        f"**Số lần chạy:** {len(run_results)} / 3  ",
        "",
        "---",
        "",
        "## 1. Bảng Kết Quả Các Lần Chạy Độc Lập",
        "",
        "| Run # | Trạng thái cuối | Số vòng | Blocking Issues (Resolved/Total) | Reviewer Schema Errors | Tổng Token | Chi phí thực tế (USD) | Thời gian (s) |",
        "| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]

    for r in run_results:
        err_desc = "0 lỗi" if not r.get("schema_errors") else f"{len(r['schema_errors'])} lỗi"
        md_lines.append(
            f"| Run {r['run_index']} | **`{r['status']}`** | {r.get('rounds', 0)} | "
            f"{r.get('blocking_resolved', 0)}/{r.get('blocking_total', 0)} | "
            f"{err_desc} | {r.get('total_tokens', 0):,} | ${r.get('total_cost_usd', 0.0):.4f} | "
            f"{r.get('elapsed_seconds', 0.0):.1f}s |"
        )

    md_lines.extend([
        "",
        "---",
        "",
        "## 2. Chi Tiết Lỗi Schema & Phản Hồi của Reviewer",
        "",
    ])

    all_schema_errors = []
    for r in run_results:
        for err in r.get("schema_errors", []):
            all_schema_errors.append((r["run_index"], err))

    if not all_schema_errors:
        md_lines.append("Không ghi nhận lỗi vi phạm schema nào từ Reviewer trong các lần chạy.")
    else:
        for run_idx, err in all_schema_errors:
            md_lines.append(f"- **Run {run_idx}** (`{err.get('role', 'reviewer')}`): {err.get('error')}")

    md_lines.extend([
        "",
        "---",
        "",
        "## 3. So Sánh Mức Tiêu Thụ Thực Tế Với Dự Trù Reserve (4.000 tokens)",
        "",
        "| Run # | Tổng Model Calls | Tokens Thực Tế TB/Call | Reserve Cố Định | Chênh Lệch | Đánh Giá Nguy Cơ Vượt Trần |",
        "| :---: | :---: | :---: | :---: | :---: | :--- |",
    ])

    for r in run_results:
        calls = r.get("model_calls_count", 0)
        tokens = r.get("total_tokens", 0)
        avg = (tokens / calls) if calls > 0 else 0
        diff = avg - 4000
        diff_str = f"+{diff:.0f}" if diff > 0 else f"{diff:.0f}"
        risk = "Có nguy cơ (Context lớn)" if avg > 3500 else "An toàn (Nằm dưới reserve 4k)"
        md_lines.append(
            f"| Run {r['run_index']} | {calls} | {avg:.0f} | 4,000 | {diff_str} tokens | {risk} |"
        )

    md_lines.extend([
        "",
        "---",
        "",
        "## 4. Đề Xuất Khắc Phục (Lỗi lặp lại $\\ge$ 2 lần)",
        "",
    ])

    # Analyze recurring errors
    if len(all_schema_errors) >= 2:
        md_lines.append("1. **Khắc phục lỗi schema của Reviewer:** Cần bổ sung few-shot schema validation hoặc tăng cường output repair tại gateway.")
    else:
        md_lines.append("Không có lỗi schema nào lặp lại $\\ge 2$ lần.")

    md_lines.append("")

    out_file = Path(args.markdown_out)
    out_file.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"\nĐã xuất báo cáo chi tiết ra: {out_file.resolve()}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
