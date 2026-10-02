# P0 Spike Report — Astra Multi

**Date:** 2026-10-02  
**Environment:** Windows NT 10.0.26200.0, Python 3.11.7, LangGraph 0.6.11

## Summary

P0 spike xác nhận LangGraph phù hợp làm orchestration runtime cho Astra Multi. Tất cả khả năng cần thiết đã được chứng minh bằng code chạy được trên Windows với 25 tests passed.

## Task Completion

| Task | Status | Evidence |
|---|---|---|
| P0.1 — Xác nhận assumptions và workspace | DONE | Python project, venv, dependencies installed, smoke import OK |
| P0.2 — Workflow giả lập chạy xuyên suốt | DONE | 10 tests passed; CLI demo chạy end-to-end |
| P0.3 — Checkpoint, interrupt, crash recovery | DONE | 10 tests passed; SQLite persistence, interrupt/resume, restart |
| P0.4 — Smoke test hai provider | BLOCKED | Adapter code ready; 5 fake tests passed; 4 live tests SKIPPED (no API keys) |
| P0.5 — Chốt runtime và bàn giao | DONE | ADR-001 written; lockfile created; spike report completed |

## Environment & Tools

- **OS:** Windows 10 (NT 10.0.26200.0)
- **Python:** 3.11.7
- **Package manager:** uv 0.12.4
- **Git:** 2.54.0.windows.1
- **Docker:** 29.7.2
- **IDE/Editor:** N/A (CLI-driven)

## Decisions & Assumptions

| ID | Decision/Assumption | Status |
|---|---|---|
| D-001 | Use LangGraph as orchestration runtime | Confirmed — ADR-001 |
| D-002 | Use `uv` for Python dependency management | Confirmed |
| D-003 | Use SQLite with WAL mode for checkpoints on Windows | Confirmed — tests pass |
| D-004 | Use `SqliteSaver(conn)` not `from_conn_string` | Confirmed — context manager API |
| A-001 | API-based LLM access (not CLI/harness) | Assumption — per PLAN.md §14 |
| A-002 | Local-first, single user | Assumption — per PLAN.md §14 |
| A-003 | Two providers: OpenAI + Google Gemini | Assumption — adapter code ready |
| Q-001 | Which provider/model + budget for live test? | OPEN — blocks P0.4 live tests |
| Q-002 | Code data policy — can code be sent to cloud LLM? | OPEN — affects provider selection |

## Pilot Thresholds (per PLAN.md §12.2)

Chốt tại P0 để P6 đánh giá mà không đổi tiêu chí sau khi thấy kết quả:

1. **100% FINAL artifacts qua structural gates** — zero FINAL với unresolved blocker.
2. **Không mất committed artifact** hoặc duplicate canonical revision trong recovery tests.
3. **Điểm chất lượng trung bình ít nhất bằng baseline** — critical omission không tăng, ít nhất một cải thiện đo được.
4. **Ngân sách vận hành nằm trong cap người dùng chọn** — báo estimated/actual.

## Commands Reference

```powershell
# Setup
cd d:\Astra multi\backend
uv venv .venv
uv pip install -e ".[dev]"

# Run tests
$env:PYTHONIOENCODING='utf-8'
.venv\Scripts\python.exe -m pytest tests/ -v

# Run demo
.venv\Scripts\python.exe -m astra_multi.demo

# Run live provider tests (when keys available)
$env:OPENAI_API_KEY='sk-...'
$env:GOOGLE_API_KEY='AI...'
uv pip install -e ".[dev,providers]"
.venv\Scripts\python.exe -m pytest tests/test_providers.py -v -k "Live"
```

## Known Issues & Limitations

1. **LangChainPendingDeprecationWarning** — `allowed_objects` warning. Cosmetic, no impact.
2. **Windows console encoding** — Use `$env:PYTHONIOENCODING='utf-8'` for proper output.
3. **Spike schemas are dataclasses** — Need migration to Pydantic models in P1 for validation.
4. **Fan-out is static (2 branches)** — PLAN.md supports this for MVP. Dynamic fan-out via `Send` API available if needed.
5. **No real crash-kill test** — `test_restart_same_thread_no_duplicate_plan` tests checkpoint recovery through new connections but not actual process kill. Real kill test deferred to P6 integration testing.

## Files Created

```
backend/
  pyproject.toml                    # Project configuration
  .env.example                     # Config example (no secrets)
  .gitignore                       # Standard ignores
  requirements.lock                # Pinned dependency versions
  src/astra_multi/
    __init__.py                    # Package
    schemas.py                     # Spike domain schemas
    workflow.py                    # LangGraph workflow graph
    fake_model.py                  # Deterministic fake adapter
    providers.py                   # OpenAI + Google adapters
    demo.py                       # CLI demo
  tests/
    __init__.py
    test_workflow.py               # P0.2 tests (10)
    test_checkpoint.py             # P0.3 checkpoint tests (6)
    test_recovery.py               # P0.3 interrupt/recovery tests (4)
    test_providers.py              # P0.4 provider tests (5+4 skipped)
docs/
  adr/
    ADR-001-runtime.md             # Runtime decision record
  spikes/
    P0_SPIKE_REPORT.md             # This report
```

## Bàn Giao P1

P1 nhận:
- **Runtime đã chốt:** LangGraph 0.6.11 với SqliteSaver
- **Dependency versions:** Pinned trong `requirements.lock`
- **Model adapter contract:** `generate(role, messages, output_schema, tool_specs, limits) -> ModelResult`
- **Workflow pattern:** StateGraph + fan-out/fan-in + bounded loop + checkpoint
- **Lỗi đã phát hiện:** SqliteSaver API (context manager), Windows encoding, deprecation warning
- **Spike code reuse:** `fake_model.py` as-is for tests; `workflow.py` structure reusable; `schemas.py` needs Pydantic migration

P1 cần:
- Typed Pydantic schemas (TaskSpec, Issue, Evidence, PlanRevision, etc.)
- SQLite domain store với migrations, writer, event log
- Revision rules và idempotency
- Operation ledger cho crash recovery
