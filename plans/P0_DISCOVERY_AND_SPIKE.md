# P0 — Khóa yêu cầu và thử nghiệm kiến trúc

Trạng thái: DONE — P0.4 đạt phạm vi người dùng cập nhật với xKiro live và Windows native; direct OpenAI/Google live còn NOT_RUN. Xem [trạng thái triển khai](../IMPLEMENTATION_STATUS.md).

## 1. Mục tiêu và đầu vào

Chứng minh lõi điều phối có thể chạy trước khi đầu tư xây sản phẩm. Đọc [PLAN.md](../PLAN.md), mục 1–5, 11, 12 và 14; quy tắc làm việc ở [IMPLEMENTATION_PLAN.md](../IMPLEMENTATION_PLAN.md).

Đầu vào: bộ tài liệu hiện tại, môi trường Windows, thông tin provider/hạ tầng khi có. Đầu ra: spike runnable, kết quả thử nghiệm và ADR-001 chốt runtime.

Vùng code dự kiến: `backend/`, `backend/tests/`, `docs/spikes/`, `docs/adr/`.

## 2. Tasks

### P0.1 — Xác nhận assumptions và chuẩn bị workspace

- **Phụ thuộc:** không có.
- **Thực hiện:** khảo sát công cụ Python/package manager, repo hiện tại và hướng dẫn dự án nếu có; ghi nhận API-vs-CLI, provider, budget, data policy, target OS; chọn cách quản lý dependency và cấu hình secrets; chốt ngưỡng pilot theo PLAN.md mục 12.2 để P6 đánh giá mà không đổi tiêu chí sau khi thấy kết quả.
- **Contract:** cấu hình công khai chỉ chứa tên provider/model và giới hạn; secrets lấy từ môi trường. Chi tiết chưa xác nhận phải là assumption hoặc question có owner.
- **Đầu ra:** tài liệu decisions/assumptions, project Python tối thiểu, config example, quy ước commands và test runner.
- **Nghiệm thu:** có lệnh khởi động/check môi trường thực tế; không có secret trong tài liệu/config; mỗi unknown ảnh hưởng thiết kế được ghi rõ.
- **Kiểm chứng:** cài dependency trong môi trường riêng và chạy smoke import. Thiếu provider không chặn fake spike P0.2 nhưng chặn live test P0.4.

### P0.2 — Workflow giả lập chạy xuyên suốt

- **Phụ thuộc:** P0.1 đủ môi trường chạy.
- **Thực hiện:** tạo schemas tối thiểu và fake model adapter; graph intake → independent analysis → propose → review → revise → gate → export; fan-out hai phân tích, fan-in deterministic.
- **Contract:** `generate(role, messages, output_schema, tool_specs, limits) -> ModelResult`; controller quyết định routing; output fake xác định theo fixture. Schema spike là bản tối thiểu cần đối chiếu lại ở P1.
- **Đầu ra:** CLI/demo và fixtures cho happy path, blocker được sửa, blocker không giải quyết.
- **Nghiệm thu:** Reviewer vòng đầu không nhận output Planner; cùng fixture cho cùng kết quả hợp nhất dù thứ tự hoàn thành khác nhau; loop có giới hạn; unresolved blocker trả PARTIAL; JSON/Markdown tối thiểu cùng nội dung.
- **Kiểm chứng:** test input isolation bằng marker; thay delay hai nhánh; kiểm tra round count và trạng thái đầu ra. Chạy không cần API key.

### P0.3 — Checkpoint, interrupt và crash recovery thử nghiệm

- **Phụ thuộc:** P0.2.
- **Thực hiện:** lưu checkpoint trên đĩa; tạm dừng khi có câu hỏi; resume cùng thread/run; tạo operation ledger nhỏ để thử crash giữa domain commit và graph checkpoint.
- **Contract:** logical operation ID giữ nguyên khi replay; question ID xác định câu hỏi đang chờ; mutation đã commit không bị tạo lại.
- **Đầu ra:** demo restart, fault injection fixtures và ghi chú thứ tự commit/checkpoint.
- **Nghiệm thu:** restart giữ kết quả đã commit; cùng answer không tạo hai mutation; crash sau commit không tạo duplicate plan revision; stream event có thể quan sát được.
- **Kiểm chứng:** kill tiến trình thật ở điểm kiểm soát, khởi động lại và so sánh IDs/revisions; không chỉ giả lập gọi lại hàm trong cùng process.

### P0.4 — API keys, provider tùy chỉnh và native Windows

- **Phụ thuộc:** P0.2 và cấu hình/provider budget có sẵn.
- **Phạm vi cập nhật 2026-10-02:** theo yêu cầu người dùng, hoàn thiện cơ chế lưu key, giữ OpenAI/Google, hỗ trợ API key + base URL tùy chỉnh và kiểm chứng native Windows để chốt P0.4. Live smoke dùng Qwen3.8 Omni Flash và Qwen3.8 Max (Free) qua cùng gateway xKiro.
- **Thực hiện:** profile có tên, loại giao thức, model ID và base URL; lưu key trong OS credential store hoặc tham chiếu biến môi trường; yêu cầu output có schema và ghi usage, latency, lỗi.
- **Contract:** key không vào metadata/log/report/CLI arguments; domain schema không import SDK provider; local validation áp dụng cả khi endpoint không hỗ trợ JSON mode.
- **Đầu ra:** hướng dẫn cấu hình/rotate/remove, báo cáo live smoke và bằng chứng Windows native; capability registry và production orchestration tiếp tục ở P3.
- **Nghiệm thu:** key lifecycle và profile isolation đạt; hai model xKiro tạo text/JSON parse/validate được; usage thiếu giữ unknown; timeout/error có mã rõ ràng; full suite, credential store và crash/recovery đạt trên Windows thật.
- **Kiểm chứng:** tối đa một text và một JSON request mỗi model, retry 0; protocol/error/schema dùng SDK thật với HTTPX MockTransport; Windows dùng credential tổng hợp và kill interpreter thật tại durability boundary. Direct OpenAI/Google live vẫn NOT_RUN nếu thiếu key riêng, không suy ra từ mock.

### P0.5 — Chốt runtime và bàn giao

- **Phụ thuộc:** P0.2–P0.4 đạt.
- **Thực hiện:** đối chiếu checklist PLAN.md mục 3.3; kiểm tra giấy phép, version, maintenance và tương thích; chốt dependency lockfile; quyết định phần spike tái sử dụng.
- **Đầu ra:** `docs/adr/ADR-001-runtime.md`, spike report, setup instructions và status cập nhật.
- **Nghiệm thu:** mỗi khả năng runtime có bằng chứng hoặc lỗi cụ thể; ADR chọn LangGraph hoặc nêu phương án thay thế cần thử. Nếu runtime fail, mở task spike khắc phục, chưa mở P1 trên giả định đã đạt.
- **Kiểm chứng:** chạy lại bộ spike sau khi khóa version.

## 3. Exit gate và bàn giao P1

- [x] Fake workflow có kết quả end-to-end.
- [x] Independent analysis, bounded loop, fan-in, persistence, interrupt/resume và stream đã kiểm chứng.
- [x] Recovery không nhân đôi artifact đã commit trong kịch bản thử nghiệm.
- [x] P0.4 theo phạm vi cập nhật: lưu key an toàn, profile tùy chỉnh, hai model xKiro live và Windows native đạt.
- [x] ADR-001, versions, commands, hạn chế và quyết định tái sử dụng được ghi lại.

P1 nhận runtime đã chốt và contracts thử nghiệm, sau đó xây domain/persistence hoàn chỉnh. Tổng quan dependency ở [implementation plan](../IMPLEMENTATION_PLAN.md).
