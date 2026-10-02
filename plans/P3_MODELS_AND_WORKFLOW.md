# P3 — Model gateway và workflow thảo luận

Trạng thái: TODO. Ước lượng: 4–6 ngày công.

## 1. Mục tiêu và dependency

Tạo luồng CLI thực tế từ yêu cầu đến candidate plan, có phản biện, kiểm chứng, câu hỏi và giới hạn. Đọc [PLAN.md](../PLAN.md), mục 4–7, 9 và 12.

P3.1–P3.2 bắt đầu sau P1, dùng kết quả spike P0. P3.3 cần contracts/tools P2. Exit phase yêu cầu P2 đạt. Vùng code: `providers/`, `agents/`, `orchestration/`, `observability/`, application services và CLI.

## 2. Tasks

### P3.1 — Model gateway dùng được trong sản phẩm

- **Phụ thuộc:** P1.5, spike P0.4.
- **Thực hiện:** hai provider adapters, capability registry, schema validation, usage mapping, config theo role; phân loại lỗi; transient retry, timeout và output-repair giới hạn. Mọi attempt đi qua budget hook, hoàn thiện ở P3.4.
- **Contract:** ModelResult ghi actual provider/model, prompt/schema versions, usage và cost estimate/actual; không đổi provider vượt policy; domain không import SDK.
- **Đầu ra:** gateway, adapter contract tests, fake providers và ADR-004.
- **Nghiệm thu:** auth không bị retry như 429; invalid output không vào domain; schema repair tối đa một lần; transient retry tối đa hai lần mặc định; mỗi attempt có trace.
- **Kiểm chứng:** deterministic fake lỗi, integration adapter mapping và live smoke nhỏ cho provider đã cấu hình.

### P3.2 — Role prompts và context contracts

- **Phụ thuộc:** P3.1, P1 schemas; tích hợp context P2.3 trước P3.3.
- **Thực hiện:** versioned prompts và output schemas cho Planner/Reviewer/Synthesizer; context riêng cho independent analysis, proposal, review, revision và synthesis.
- **Contract:** vòng độc lập không thấy peer output; agents gửi proposals/deltas, không ghi canonical state; issue có claim, severity, impact, căn cứ hoặc verification request.
- **Đầu ra:** role contract docs, prompt versions, context fixtures.
- **Nghiệm thu:** không có quyền đổi budget/routing trong output schema; không lẫn context của run khác; phần summary giữ evidence IDs.
- **Kiểm chứng:** marker isolation, input snapshots theo phase và malformed role output.

### P3.3 — Workflow tích hợp domain và tools

- **Phụ thuộc:** P3.1–P3.2, P2.5.
- **Thực hiện:** graph intake/snapshot/investigate/independent/propose/review/verify/revise/synthesize; fan-in stable; issue routing theo dữ kiện, thiết kế, sản phẩm; questions và answers có version; semantic review interface cho P4.
- **Contract:** controller commit qua P1; decisions có alternatives/rationale; blocking issue resolution được reviewer kiểm tra trên revision mới; user sửa requirement tạo TaskSpec revision mới và invalidates review/coverage liên quan.
- **Đầu ra:** graph nodes/reducers, application command handlers và ADR-003.
- **Nghiệm thu:** thực hiện được greenfield và repo task; thiếu thông tin kiến trúc chuyển WAITING_FOR_INPUT; evidence mới gắn đúng issue; answer trùng/stale không tạo mutation trùng.
- **Kiểm chứng:** fixtures happy path, disagree→verify→revise, ask→answer→resume, changed requirement, sandbox unavailable. Tại phase này candidate chưa được công bố FINAL nếu quality service P4 chưa sẵn sàng.

### P3.4 — Budget, stop conditions và cancellation

- **Phụ thuộc:** P3.1, P3.3.
- **Thực hiện:** atomic reservations cho call song song; reconcile usage, retries/output repair tính phí; token/call/deadline/round limits; stagnation detector; cancel scheduling và cleanup tool job.
- **Contract:** stop reason typed; budget exhaustion không biến blocker thành resolved; lưu draft và đủ resources để xuất partial; cancelled attempt giữ usage đã biết, reservation chưa chắc chắn được đánh dấu pending/estimated thay vì hoàn ngay một cách sai lệch.
- **Đầu ra:** budget service, termination policies và phần budget của ADR-006.
- **Nghiệm thu:** concurrent calls không reserve quá cap; retry bị chặn khi không đủ ngân sách; lặp không evidence/resolution mới dừng có lý do; cancel không nhận late output để tiến trạng thái thành công.
- **Kiểm chứng:** barrier-based concurrency test, clock giả cho deadline, provider trả usage thiếu, cancel giữa model/tool call và crash khi còn reservation.

### P3.5 — CLI end-to-end và recovery workflow

- **Phụ thuộc:** P3.1–P3.4.
- **Thực hiện:** CLI tạo run, status, answer/resume, cancel và lấy candidate artifacts; kết nối checkpoint/revision/lease P1; ghi model/tool event và redaction.
- **Đầu ra:** CLI runnable, walkthrough, integration/recovery report.
- **Nghiệm thu:** restart resume đúng run/revision; không duplicate decisions; một run hoạt động theo policy MVP; diagnostics không lộ key; hai provider có thể cấu hình theo role.
- **Kiểm chứng:** fake full workflow và một run live có budget; kill/restart tại revision boundary; assertions độc lập vòng đầu và bounded loops.

## 3. Exit gate

- [ ] Luồng CLI tích hợp repo/tool/model chạy được.
- [ ] Independent analysis, issue resolution, questions và revisions đúng contract.
- [ ] Budget, retry, timeout, stagnation và cancel có test hành vi.
- [ ] Resume dựa trên committed state, không nhân đôi canonical artifact.
- [ ] Candidate/partial artifacts sẵn cho P4; ADR-003/004 và budget decisions được ghi.

**Bàn giao P4:** PlanCandidate, issues/decisions/evidence refs, semantic review interface, stop reasons, usage và application service API. Cập nhật [status](../IMPLEMENTATION_STATUS.md).
