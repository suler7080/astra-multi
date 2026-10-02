# P5 — API và giao diện sử dụng local

Trạng thái: TODO. Ước lượng: 4–6 ngày công. Prerequisite: P4 đạt.

## 1. Mục tiêu

Người dùng tạo run, theo dõi phản biện, trả lời câu hỏi và nhận plan qua ứng dụng local. Tham chiếu [PLAN.md](../PLAN.md), mục 4.2, 8 và 9. Vùng code: `api/`, worker startup, `frontend/`.

## 2. Tasks

### P5.1 — API commands và queries

- **Phụ thuộc:** P4.4.
- **Thực hiện:** FastAPI endpoints theo PLAN.md: create/status/issues/evidence/plans/answers/resume/cancel/export; local session/token, origin policy, request validation và error envelope.
- **Contract:** create trả 202 + run ID sau durable enqueue; idempotency key cùng payload trả cùng run, khác payload trả conflict. Answers có question ID và expected revision. Export nhận revision tường minh để tải cố định.
- **Đầu ra:** OpenAPI, API handlers dùng application services có sẵn, integration tests.
- **Nghiệm thu:** HTTP không giữ tới hết run; invalid_state/revision_conflict có code; thiếu auth bị từ chối; API key provider không trả frontend; đường dẫn artifact đi qua scoped resolver.
- **Kiểm chứng:** request tests với app và DB thật, duplicate create/answer, invalid revision, auth/origin và artifact access ngoài run.

### P5.2 — Worker lifecycle và SSE

- **Phụ thuộc:** P5.1, event/lease service P1.
- **Thực hiện:** worker claim queued run theo lease; SSE replay từ Last-Event-ID và live tail; heartbeat, disconnect cleanup và bounded buffering.
- **Contract:** event ID/sequence ổn định; replay→live không bỏ khoảng trống; client dedup theo ID; disconnect UI không cancel run; event payload không lộ secrets hoặc nội dung reasoning ẩn.
- **Đầu ra:** worker entrypoint, event stream endpoint và reconnect protocol.
- **Nghiệm thu:** reload UI thấy trạng thái mới nhất; worker restart xử lý tiếp run đã lưu; hai workers không cùng ghi; slow client không làm tăng bộ nhớ vô hạn.
- **Kiểm chứng:** disconnect đúng thời điểm replay/live, stale/invalid event ID, worker restart và delayed consumer.

### P5.3 — New run, overview và human input

- **Phụ thuộc:** P5.1–P5.2.
- **Thực hiện:** React/TypeScript/Vite app; form yêu cầu/repo/models/budget, run overview, pending question, answers/resume/cancel; loading/empty/error states.
- **Contract:** frontend dùng typed API client; backend là nguồn trạng thái; UI không tự quyết FINAL; submit tránh double request nhưng correctness vẫn dựa backend idempotency.
- **Đầu ra:** run creation/detail screens và accessible forms.
- **Nghiệm thu:** người dùng tạo run, xem tiến trình, trả lời và tiếp tục được; refresh giữ run ID; lỗi revision/cấu hình có thông báo hành động cụ thể; thao tác bằng bàn phím được.
- **Kiểm chứng:** browser E2E với fake model backend, pause→answer→resume, cancel, API unavailable và reload.

### P5.4 — Discussion, issues, evidence và plan revisions

- **Phụ thuộc:** P5.3.
- **Thực hiện:** timeline theo phase/role, issue table/status, evidence source viewer, decision log, coverage, revision diff và dependency view; tải JSON/Markdown theo revision.
- **Contract:** UI chỉ render nội dung công khai đã lưu; text/code/Markdown xử lý an toàn; diff theo stable IDs trước khi diff text; lớn thì phân trang/tham chiếu artifact.
- **Đầu ra:** views giúp truy từ requirement đến step/validation/evidence.
- **Nghiệm thu:** FINAL/PARTIAL và stop reason rõ; NOT_RUN không hiển thị PASS; actual/estimated cost phân biệt; chọn revision cũ không bị auto thay trong lúc tải.
- **Kiểm chứng:** fixtures nhiều revisions, evidence truncated, unknown usage, Markdown chứa HTML/script và Unicode.

### P5.5 — Walkthrough end-to-end và setup local

- **Phụ thuộc:** P5.1–P5.4.
- **Thực hiện:** startup/shutdown instructions, sample config, lỗi cổng/DB/provider/runner; chạy user journeys với fake và một live run trong budget.
- **Đầu ra:** local setup guide, E2E report và demo artifacts.
- **Nghiệm thu:** từ mở app đến export được FINAL hoặc PARTIAL đúng dữ kiện; restart sau WAITING vẫn trả lời được; source repo không đổi; secrets không xuất hiện ở UI/log.
- **Kiểm chứng:** create→review→question→resume→export, blocker→PARTIAL, disconnect/reconnect và cancel. Ghi command/ports thực tế sau implementation.

## 3. Exit gate

- [ ] API đúng contract và dùng domain services chung với CLI.
- [ ] Durable worker và SSE reconnect được kiểm chứng.
- [ ] UI hoàn thành các user journeys có error states.
- [ ] Local setup chạy lại được từ hướng dẫn.
- [ ] API schemas, UI version và run artifacts sẵn cho benchmark P6.

**Bàn giao P6:** application build/config cố định, OpenAPI/SSE contracts, startup commands, sample run exports và danh sách lỗi còn mở. Cập nhật [status](../IMPLEMENTATION_STATUS.md).
