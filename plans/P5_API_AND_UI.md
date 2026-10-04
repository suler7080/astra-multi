# P5 — API và giao diện sử dụng local

Trạng thái: DONE. Prerequisite: P4 đạt.

## 1. Mục tiêu

Người dùng tạo run, theo dõi phản biện, trả lời câu hỏi và nhận plan qua ứng dụng local. Tham chiếu [PLAN.md](../PLAN.md), mục 4.2, 8 và 9. Vùng code: `src/astra_multi/api/`, worker lifecycle, `frontend/`.

## 2. Tasks

### P5.1 — API commands và queries (Hoàn thành)

- **Thực hiện:** Đầy đủ FastAPI endpoints (`POST /api/runs`, `GET /api/runs`, `GET /api/runs/{id}`, `/issues`, `/evidence`, `/decisions`, `/plans/{rev}`, `/answers`, `/resume`, `/cancel`, `/export`, `/validate`, `/finalize`); CORS middleware, Idempotency-Key support, error envelope và revision conflict verification.
- **Contract:** Create trả 202 + `run_id` sau durable enqueue; idempotency key cùng payload trả cùng run, khác payload trả 409 Conflict. Answer có `question_id` và `expected_revision`. Export nhận `revision` tường minh tải JSON hoặc Markdown.

### P5.2 — Worker lifecycle và SSE (Hoàn thành)

- **Thực hiện:** Background worker `RunWorker` claim run theo lease và chạy workflow graph trong worker thread pool; endpoint `GET /api/runs/{id}/events` stream Server-Sent Events với replay từ `Last-Event-ID` hoặc query `last_event_id` và live tail; graceful shutdown và lease release.
- **Contract:** Event sequence ổn định; replay->live không khoảng trống; terminal run gửi `run_completed` và đóng stream.

### P5.3 — New run, overview và human input (Hoàn thành)

- **Thực hiện:** React 18 + TypeScript + Vite app trong `frontend/`; form tạo run với goal, requirements động, mode selection (greenfield/repo), budget limits, max rounds; pending question banner với input trả lời trực tiếp và resume prompt; modal validate/finalize.
- **Contract:** Frontend dùng typed API client (`frontend/src/api.ts`); URL query params giữ `?run=RUN_ID` khi reload; backend idempotency; accessible keyboard navigation.

### P5.4 — Discussion, issues, evidence và plan revisions (Hoàn thành)

- **Thực hiện:** Visual 10-phase tracker, Discussion timeline với role badges (Planner, Reviewer, Synthesizer, Verifier, Operator) và auto-scroll; Issues table với bộ lọc severity/status; Decisions log với rationale và rejected alternatives; Evidence ledger phân biệt NOT_RUN / PASS / FAIL; Plan viewer hiển thị từng revision với deliverables, dependencies và validation commands; Download Markdown / JSON.

### P5.5 — Walkthrough end-to-end và setup local (Hoàn thành)

- **Thực hiện:** Tích hợp CLI subcommand `astra-multi serve --host 127.0.0.1 --port 8000`; FastAPI tự động mount `frontend/dist` tại `/` khi đã build; kiểm thử tích hợp toàn diện qua `test_api.py`.
- **Command khởi chạy:**
  ```powershell
  # Build frontend
  cd "D:\Astra multi\frontend"
  npm run build

  # Chạy server (gồm cả API và UI)
  cd "D:\Astra multi\backend"
  .venv\Scripts\python -m astra_multi.cli serve --host 127.0.0.1 --port 8000
  ```

## 3. Exit gate

- [x] API đúng contract và dùng domain services chung với CLI.
- [x] Durable worker và SSE reconnect được kiểm chứng.
- [x] UI hoàn thành các user journeys có error states.
- [x] Local setup chạy lại được từ hướng dẫn.
- [x] API schemas, UI version và run artifacts sẵn cho benchmark P6.

**Bàn giao P6:** application build/config cố định, OpenAPI/SSE contracts, startup commands, sample run exports và danh sách lỗi còn mở. Cập nhật [status](../IMPLEMENTATION_STATUS.md).
