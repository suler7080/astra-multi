# P4 — Quality gates và xuất kế hoạch

Trạng thái: TODO. Ước lượng: 2–3 ngày công. Prerequisite: P3 đạt.

## 1. Mục tiêu

Chỉ công bố FINAL khi kế hoạch vượt qua điều kiện cấu trúc và review ngữ nghĩa; JSON/Markdown dùng chung nguồn chuẩn. Tham chiếu [PLAN.md](../PLAN.md), mục 9, và [PLAN_TEMPLATE.md](../PLAN_TEMPLATE.md).

Vùng code: `domain/` policies, `exports/`, orchestration gate node, fixtures kế hoạch.

## 2. Tasks

### P4.1 — Structural quality validator

- **Phụ thuộc:** P3.5.
- **Thực hiện:** validate schemas, unique IDs, reference integrity, requirement→step→validation coverage, step fields, dependency DAG, snapshot/evidence consistency và validation execution status.
- **Contract:** `validate(candidate, task, issues, evidence) -> QualityReport`; report có rule ID, severity, entity reference, message và remediation. Greenfield không đòi bằng chứng code chưa tồn tại; claim về repo hiện hữu phải có nguồn phù hợp.
- **Đầu ra:** deterministic validators, coverage report và invalid plan fixtures.
- **Nghiệm thu:** bắt được cycle, dangling ref, missing requirement, wrong snapshot, giả PASS; lỗi chỉ rõ vị trí; validator không tự sửa hoặc loại requirement để pass.
- **Kiểm chứng:** mỗi invariant có valid/invalid fixture, gồm nhiều requirement dùng chung step và validation nhiều bước.

### P4.2 — Semantic review và finalization policy

- **Phụ thuộc:** P4.1 và semantic review interface P3.
- **Thực hiện:** rubric feasibility, correctness, validation strength, compatibility/migration khi liên quan, proportionality; semantic concerns tạo issues; controller quyết định FINAL/PARTIAL/WAITING/FAILED/CANCELLED.
- **Contract:** FINAL cần structural pass, review trên đúng revision, không unresolved blocker/question ảnh hưởng kiến trúc; sửa candidate làm review cũ mất hiệu lực. Tổng hợp không tự đổi severity để vượt gate.
- **Đầu ra:** finalization service, state mapping và ADR-006 hoàn chỉnh.
- **Nghiệm thu:** model nói “đồng ý” không ghi đè validator; hết budget với blocker là PARTIAL; lỗi reviewer không coi như review pass; assumptions còn lại được hiển thị.
- **Kiểm chứng:** fake reviewer cho contradiction, stale review, unavailable review, resolved/reopened issue và thiếu câu trả lời quan trọng.

### P4.3 — Canonical JSON và Markdown exporter

- **Phụ thuộc:** P4.1–P4.2.
- **Thực hiện:** immutable finalized revision, versioned export schema, render theo template; decision log, evidence index, open questions, coverage, actual/estimated usage.
- **Contract:** exporter nhận revision cụ thể và canonical object; không gọi LLM viết lại; Markdown text được escape phù hợp, không nhúng nội dung HTML thực thi. Export PARTIAL vẫn nêu blockers và next actions.
- **Đầu ra:** JSON serializer, Markdown renderer, artifact manifest/hash.
- **Nghiệm thu:** requirement/step IDs, status, decisions và validation khớp hai định dạng; export đang tải không đổi khi run có revision mới; path chưa xác định được ghi unknown/discovery task thay vì giả file tồn tại.
- **Kiểm chứng:** semantic parity tests, Unicode tiếng Việt, bảng/code blocks có ký tự đặc biệt và concurrent revision export.

### P4.4 — Plan handoff end-to-end

- **Phụ thuộc:** P4.1–P4.3.
- **Thực hiện:** nối gate/export vào CLI P3; tạo mẫu FINAL và PARTIAL; rà theo PLAN_TEMPLATE; tài liệu hóa commands/queries để P5 gọi lại.
- **Đầu ra:** hai sample exports, integration report, public application service contract.
- **Nghiệm thu:** từ TaskSpec đến artifact export qua cùng pipeline; sample FINAL truy vết mọi requirement; sample PARTIAL nêu chính xác thiếu gì để tiếp tục; UI sau này không cần sao chép quality logic.
- **Kiểm chứng:** một fixture full success và một fixture hết vòng/budget với unresolved blocker; mở/read lại exports từ storage.

## 3. Exit gate

- [ ] Structural gates và semantic review đã tích hợp.
- [ ] Không FINAL khi blocker/review stale/gate failure tồn tại.
- [ ] JSON/Markdown nhất quán theo revision cố định.
- [ ] CLI tạo được plan bàn giao đầy đủ theo template.
- [ ] ADR-006 và service contracts đã ghi lại.

**Bàn giao P5:** commands/queries, QualityReport, immutable revision export, sample artifacts và status semantics. Cập nhật [status](../IMPLEMENTATION_STATUS.md).
