# Astra Multi — Trạng thái triển khai

Ngày khởi tạo: 01/10/2026.

## Hiện trạng

- Đã hoàn thành P0 spike — chứng minh runtime khả thi.
- ADR-001 đã chốt: LangGraph 0.6.11.
- P1 contracts, canonical SQLite store và recovery đã triển khai; 229 tests passed, 4 skipped (live provider — BLOCKED), lint/typecheck/build đạt trên Linux Python 3.11.
- Phase hoàn thành: **P1 DONE**; P0.4 vẫn BLOCKED do thiếu API keys, không coi mock là bằng chứng provider thật.
- Task tiếp theo: **P2.1 / P3.1**, dùng [public contracts](docs/P1_CONTRACTS.md); native Windows chưa được kiểm chứng trong phiên này.

## Task board

| Phase | Task | Trạng thái | Ghi chú |
|---|---|---|---|
| P0 | P0.1 | DONE | Python project, venv, deps, smoke import |
| P0 | P0.2 | DONE | Workflow fake end-to-end, 10 tests passed |
| P0 | P0.3 | DONE | Checkpoint, interrupt/resume, recovery, 10 tests passed |
| P0 | P0.4 | BLOCKED | Adapter code ready; live tests need API keys |
| P0 | P0.5 | DONE | ADR-001, spike report, lockfile, handoff docs |
| P1 | P1.1 | DONE | Typed schemas v1, repo/greenfield fixtures, required fields/enums, refs/DAG, UTC, JSON samples |
| P1 | P1.2 | DONE | Revision conflicts, transition tables, issue history/resolution/provenance, pending questions; FINAL dành P4 |
| P1 | P1.3 | DONE | SQLite migration v1, atomic state/event/ledger, idempotency, hash artifacts và rollback |
| P1 | P1.4 | DONE | Lease token/epoch fencing, heartbeat/takeover, subprocess kill/restart và contention; ADR-002 |
| P1 | P1.5 | DONE | Repository protocols, checkpoint refs, sample client restart, schemas/samples, contracts docs; spike dùng domain models |
| P2 | P2.1, P2.2, P2.3, P2.4, P2.5 | Tất cả TODO | |
| P3 | P3.1, P3.2, P3.3, P3.4, P3.5 | Tất cả TODO | |
| P4 | P4.1, P4.2, P4.3, P4.4 | Tất cả TODO | |
| P5 | P5.1, P5.2, P5.3, P5.4, P5.5 | Tất cả TODO | |
| P6 | P6.1, P6.2, P6.3, P6.4 | Tất cả TODO | |

## Khả năng chạy được hiện tại

```powershell
cd d:\Astra multi\backend
$env:PYTHONIOENCODING='utf-8'

# Run all tests
.venv\Scripts\python.exe -m pytest tests/ -v

# Run workflow demo
.venv\Scripts\python.exe -m astra_multi.demo

# P1 public client (workspace mới) và schema exporter
.venv\Scripts\python.exe -m astra_multi.persistence_demo .local\p1-client
.venv\Scripts\python.exe -m astra_multi.domain.export_contracts .local\contracts
```

Lệnh đã kiểm chứng trong phiên P1 trên Linux, từ `backend`:

```sh
.venv/bin/ruff check src/astra_multi/domain src/astra_multi/persistence src/astra_multi/persistence_demo.py src/astra_multi/schemas.py src/astra_multi/fake_model.py src/astra_multi/workflow.py tests/unit tests/integration tests/recovery
.venv/bin/mypy
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m astra_multi.persistence_demo .local/p1-client
.venv/bin/python -m astra_multi.domain.export_contracts .local/contracts
uv build --python .venv/bin/python
```

## Quyết định đã chốt

- **ADR-001:** LangGraph 0.6.11 là orchestration runtime — [docs/adr/ADR-001-runtime.md](docs/adr/ADR-001-runtime.md)
- **ADR-002:** Domain store canonical, ledger idempotency và fenced lease — [docs/adr/ADR-002-domain-persistence.md](docs/adr/ADR-002-domain-persistence.md)
- **Package manager:** uv 0.12.4
- **Checkpoint:** SQLite với WAL mode, `SqliteSaver(conn)` trực tiếp
- **Pilot thresholds:** Chốt theo PLAN.md §12.2 (xem spike report)

## Quyết định còn cần chốt

- Provider/model nào cho live test và budget mỗi run.
- Code data policy — gửi code đến cloud LLM được không.
- Xem đầy đủ tại PLAN.md, mục 14.

## Bản ghi bàn giao

### 2026-10-02 — P0.1 — DONE
- Mục tiêu: Xác nhận assumptions, chuẩn bị workspace
- File: `backend/pyproject.toml`, `backend/.env.example`, `backend/.gitignore`, `backend/src/astra_multi/__init__.py`
- Acceptance criteria: có lệnh khởi động/check môi trường ✓; không secret trong config ✓; unknowns ghi rõ ✓
- Command: `uv venv .venv && uv pip install -e ".[dev]"` trong `d:\Astra multi\backend`
- Kết quả: Python 3.11.7, uv 0.12.4, LangGraph 0.6.11, Pydantic 2.13.5 — all imports OK
- Blocker: không có
- Task tiếp theo: P0.2

### 2026-10-02 — P0.2 — DONE
- Mục tiêu: Workflow giả lập chạy xuyên suốt
- File: `backend/src/astra_multi/schemas.py`, `workflow.py`, `fake_model.py`, `demo.py`; `backend/tests/test_workflow.py`
- Contract: `generate(role, messages, output_schema, tool_specs, limits) -> ModelResult`
- Acceptance criteria:
  - Reviewer vòng đầu không nhận output Planner ✓ (`test_planner_marker_not_in_reviewer_analysis`)
  - Cùng fixture cho cùng kết quả ✓ (`test_same_input_same_output`, `test_analyses_sorted_by_role`)
  - Loop có giới hạn ✓ (`test_respects_max_rounds`)
  - Unresolved blocker → PARTIAL ✓ (`test_unresolved_blocker_fails_gate`)
  - JSON/Markdown cùng nội dung ✓ (export node produces both)
- Command: `.venv\Scripts\python.exe -m pytest tests/test_workflow.py -v` — 10 passed
- Task tiếp theo: P0.3

### 2026-10-02 — P0.3 — DONE
- Mục tiêu: Checkpoint, interrupt, crash recovery
- File: `backend/tests/test_checkpoint.py`, `test_recovery.py`
- Acceptance criteria:
  - Restart giữ kết quả đã commit ✓ (`test_resume_after_restart_keeps_results`)
  - Cùng answer không tạo hai mutation ✓ (`test_same_thread_same_result`, `test_no_duplicate_issues_across_checkpoint`)
  - Crash sau commit không duplicate ✓ (`test_restart_same_thread_no_duplicate_plan`)
  - Stream event observable ✓ (`test_stream_updates_observable`)
  - Interrupt/resume ✓ (`test_interrupt_pauses_and_resume_continues`, `test_interrupt_persists_across_restart`)
- NOT_RUN: Kill tiến trình thật — deferred to P6 integration testing
- Command: `.venv\Scripts\python.exe -m pytest tests/test_checkpoint.py tests/test_recovery.py -v` — 10 passed
- Task tiếp theo: P0.4

### 2026-10-02 — P0.4 — BLOCKED
- Mục tiêu: Smoke test hai provider live
- File: `backend/src/astra_multi/providers.py`, `backend/tests/test_providers.py`
- Acceptance criteria:
  - Adapter routing + error classification ✓ (5 fake tests passed)
  - Live smoke test: NOT_RUN — no OPENAI_API_KEY or GOOGLE_API_KEY
- Blocker: API keys needed. Không thay bằng kết luận từ mock.
- Task tiếp theo: P0.5

### 2026-10-02 — P0.5 — DONE
- Mục tiêu: Chốt runtime và bàn giao
- File: `docs/adr/ADR-001-runtime.md`, `docs/spikes/P0_SPIKE_REPORT.md`, `backend/requirements.lock`
- Acceptance criteria:
  - Mỗi khả năng runtime có bằng chứng ✓ (ADR-001 references test names)
  - ADR chọn LangGraph ✓
  - Version locked ✓ (`requirements.lock`)
- Task tiếp theo: P1.1

### 2026-10-02 — P1.1–P1.5 — DONE

- Contracts: `backend/src/astra_multi/domain/`; public schema version 1, stable IDs, UTC, explicit snapshot null cho greenfield, references và requirement/step/evidence validation; JSON Schema và samples tại `docs/contracts/`.
- Policies: expected **run** revision trên commands; **plan** revision trên issue/proposal; issue history, independent review trên current newer plan hoặc requirement-change provenance; duplicate giữ blocker; terminal không resume; FINAL chỉ dành quality service P4.
- Storage: `backend/src/astra_multi/persistence/`; migration v1, WAL/FULL, mutation + event + OperationRecord cùng transaction, unique `(run_id, node, logical_operation_id)`, event sequence riêng per run, filesystem artifact SHA-256/fsync/atomic replace.
- Recovery: CheckpointBridge chỉ giữ refs; lease có token/epoch/expiry; heartbeat và takeover fence worker cũ. Subprocess bị kill sau mutation/event/ledger chưa commit rollback đủ; kill sau domain commit trước checkpoint rồi restart không tạo plan/event thứ hai. Hai subprocess tranh run chỉ một bên acquire thành công.
- Handoff: `domain/repositories.py` protocols, `domain/fixtures.py`, `persistence_demo.py` tạo task/run, ghi issue/plan, đóng và reopen DB qua public ports; [contract document](docs/P1_CONTRACTS.md), [ADR-002](docs/adr/ADR-002-domain-persistence.md).
- Verification: full suite **229 passed, 4 skipped**, một LangChain pending-deprecation warning; Ruff đạt trên toàn bộ source/test P1 và source P0 được sửa; strict mypy **13 source files**; P0 demo chạy thành công; sample client reopen thành công; exporter sinh JSON; wheel/sdist build thành công.
- Bằng chứng: `tests/unit/test_domain.py` (schema/round-trip, transitions, invalid resolutions, refs, SDK independence), `tests/integration/test_storage.py` (real SQLite/fault injection/artifacts/migrations/lease/public client), `tests/recovery/test_crash.py` (process kill/restart/contention, real LangGraph SQLite checkpoint).
- Giới hạn: Linux Python 3.11 đã kiểm chứng, Windows native chưa chạy; không tuyên bố exactly-once cho provider/tool ngoài DB. P0 spike vẫn dùng execution state/demo gate riêng, P3/P4 sẽ nối production orchestration/quality service vào canonical ports. P0.4 vẫn thiếu OPENAI_API_KEY và GOOGLE_API_KEY.
- Task tiếp theo: P2.1 / P3.1. Blueprint setup đã được người dùng duyệt và lưu cho các phiên sau; snapshot build mới được kích hoạt.
