# P1 — Domain contracts và persistence

Trạng thái: DONE — xem [bản ghi kiểm chứng P1](../IMPLEMENTATION_STATUS.md). Prerequisite: P0 đạt exit gate; riêng P0.4 provider live tests vẫn BLOCKED do thiếu API keys, P1 storage/recovery được kiểm chứng độc lập trên SQLite thật.

## 1. Mục tiêu

Tạo nguồn dữ liệu chuẩn, có revision và recovery đáng tin cậy. Tham chiếu [PLAN.md](../PLAN.md), mục 2, 5.4, 6 và 9. Vùng code: `backend/src/astra_multi/domain/`, `persistence/`, `tests/unit/`, `tests/integration/`, `tests/recovery/`.

## 2. Tasks

### P1.1 — Typed schemas và reference contracts

- **Phụ thuộc:** P0.5.
- **Thực hiện:** schemas cho TaskSpec, Run, Snapshot, Claim, Evidence, Proposal, Issue, Decision, PlanRevision/Step, ToolCall, ModelCall và Event; bổ sung Question, ValidationResult, BudgetReservation, OperationRecord theo nhu cầu các luồng đã thiết kế.
- **Contract:** ID ổn định, UTC timestamps, schema version, requirement/step/evidence references; trạng thái validation có NOT_RUN/PASS/FAIL; tách run phase khỏi run status. Greenfield dùng snapshot ref tùy chọn tường minh.
- **Đầu ra:** domain models, fixtures hợp lệ/không hợp lệ và schema documentation.
- **Nghiệm thu:** thiếu trường bắt buộc hoặc enum sai bị từ chối; serialize/deserialize không mất dữ liệu; SDK/framework không trở thành dependency của domain contracts.
- **Kiểm chứng:** fixture tests cho run có repo và greenfield; schema round-trip và invalid payloads.

### P1.2 — Quy tắc chuyển trạng thái và issue resolution

- **Phụ thuộc:** P1.1.
- **Thực hiện:** policies cho run transitions, revision update, issue lifecycle, resolution/rejection/duplicate và câu hỏi đang chờ.
- **Contract:** command có expected revision; đóng blocking issue cần resolution và review trên revision mới, hoặc thay đổi requirement có lưu provenance. Việc FINAL chỉ đi qua quality service, contract đầy đủ ở P4.
- **Đầu ra:** domain services/policies và bảng transition được tài liệu hóa.
- **Nghiệm thu:** không đóng issue bằng đồng thuận rỗng; stale revision bị reject; resolved issue vẫn có lịch sử; không resume run terminal như một run mới.
- **Kiểm chứng:** state transition table tests, stale commands, duplicate issue link và invalid resolution.

### P1.3 — SQLite repositories và atomic mutation

- **Phụ thuộc:** P1.1–P1.2.
- **Thực hiện:** migration có version, repository interfaces, transaction boundary; domain mutation + event + operation result ghi cùng transaction; artifacts lớn lưu filesystem với hash/ref.
- **Contract:** một writer; unique operation key `(run_id, node, logical_operation_id)`; event sequence tăng theo run. Artifact file phải ghi hoàn chỉnh trước khi commit reference, lỗi ghi không được tạo dangling reference.
- **Đầu ra:** repositories, migration runner, storage setup và artifact store.
- **Nghiệm thu:** duplicate operation trả kết quả cũ; lỗi giữa transaction rollback cả mutation/event; stale update không ghi event thành công; restart đọc được artifact/hash.
- **Kiểm chứng:** SQLite thật trong temporary workspace, transaction fault injection, migration trên DB mới và schema fixture cũ khi có migration nâng cấp.

### P1.4 — Checkpoint bridge, run lease và recovery

- **Phụ thuộc:** P1.3 và kết quả P0.3.
- **Thực hiện:** checkpoint chỉ giữ refs/revision cần thiết; adapter load/commit domain; lease + heartbeat cho worker; stale lease recovery và từ chối writer hết quyền.
- **Contract:** domain store canonical; replay không tạo plan thứ hai; lease token/epoch được kiểm tra khi mutation để worker cũ không tiếp tục ghi sau khi lease đổi chủ.
- **Đầu ra:** checkpoint bridge, lease service, recovery scenarios; ADR-002.
- **Nghiệm thu:** hai worker tranh một run chỉ một writer có quyền; worker mất lease không commit được; kill sau domain commit trước checkpoint không duplicate revision.
- **Kiểm chứng:** chạy subprocess crash/restart và contention trên DB thật; ghi rõ external provider call có thể lặp, không tuyên bố exactly-once toàn hệ thống.

### P1.5 — Public contracts và bàn giao

- **Phụ thuộc:** P1.1–P1.4.
- **Thực hiện:** xuất schema samples và repository API; dựng fixture chung cho P2/P3; chuyển phần domain của spike sang contract chính; cập nhật commands/status.
- **Đầu ra:** contracts document, shared fixtures, ADR-002 và báo cáo phase.
- **Nghiệm thu:** sample client tạo TaskSpec/run, ghi issue/revision, đóng DB và đọc lại được; không phải import SDK model để thao tác domain.
- **Kiểm chứng:** integration scenario dùng public repository interfaces.

## 3. Exit gate

- [x] Domain contracts được validate và có fixtures.
- [x] Revision, issue resolution, operation idempotency và atomic events đạt.
- [x] Recovery và single-writer lease được chứng minh trên storage thật.
- [x] P2/P3 có thể dùng interfaces mà không phụ thuộc implementation nội bộ.

**Bàn giao:** schema version, repository APIs, event envelope, ID/revision rules, operation ledger, lease semantics và commands kiểm chứng. Theo dõi tại [IMPLEMENTATION_STATUS.md](../IMPLEMENTATION_STATUS.md).
