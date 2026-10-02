# P2 — Repo snapshot, evidence và công cụ kiểm chứng

Trạng thái: TODO. Ước lượng: 3–5 ngày công. Prerequisite: P1 đạt.

## 1. Mục tiêu

Cho tất cả vai trò dùng cùng dữ kiện và dẫn nguồn được. Tham chiếu [PLAN.md](../PLAN.md), mục 6.3–6.4, 7.2 và 12.1. Vùng code: `context/`, `tools/`, `sandbox/`, fixtures repo trong `tests/`.

## 2. Tasks

### P2.1 — Snapshot service

- **Phụ thuộc:** P1.5.
- **Thực hiện:** snapshot Git clean/dirty và non-Git; manifest/hash, exclude policy, repo map; phát hiện source thay đổi trong lúc capture bằng kiểm tra hash/metadata và retry giới hạn hoặc báo capture không nhất quán.
- **Contract:** SnapshotRef trỏ nội dung đã đóng băng; dirty working tree được biểu diễn bằng nội dung thực, không chỉ commit ID; untracked files theo selection policy; ghi excluded paths/patterns. Greenfield có context không-repo rõ ràng.
- **Đầu ra:** snapshot creator/reader và fixtures clean, dirty, untracked, non-Git.
- **Nghiệm thu:** đổi source sau capture không đổi snapshot; cùng nội dung và policy cho manifest ổn định; capture đang biến đổi không âm thầm coi là consistent.
- **Kiểm chứng:** hash comparison, sửa file nguồn khi/ sau capture, paths có dấu và khoảng trắng.

### P2.2 — Read/search/list qua tool broker

- **Phụ thuộc:** P2.1.
- **Thực hiện:** tools chỉ đọc snapshot; resolve path, symlink/junction; output pagination/truncation; repo dependency/test-command inspection và fetch documentation trong scope cấu hình.
- **Contract:** ToolRequest có run/snapshot/call ID; ToolResult có locator, range, hash, output ref và truncation metadata. Web evidence lưu URL, thời điểm và hash nội dung đã lấy.
- **Đầu ra:** tool interfaces, broker, read/search adapters và document fetch adapter.
- **Nghiệm thu:** path traversal hoặc link thoát root bị chặn; đọc tiếp output được; nội dung tài liệu không thể sửa policy/controller config.
- **Kiểm chứng:** fixtures path escape, junction/symlink khi môi trường hỗ trợ, large output và local HTTP fixture/mock fetch; ghi NOT_RUN nếu thiếu quyền tạo link.

### P2.3 — Evidence ledger và context bundle

- **Phụ thuộc:** P2.2.
- **Thực hiện:** chuyển tool result thành Evidence; liên kết claim, hash, snapshot; phát hiện stale evidence; context bundle theo vai trò/phase và giới hạn token.
- **Contract:** `build_context(run, role, phase, refs, limits)` trả nội dung + source IDs + truncation/selection metadata. Baseline vòng độc lập giống nhau về dữ kiện; summaries không tự sinh fact không nguồn.
- **Đầu ra:** evidence service, context builder và selection policy.
- **Nghiệm thu:** evidence snapshot cũ không được xác nhận cho code mới; file read không biến thành test PASS; context vượt limit được xử lý rõ ràng, giữ references thiết yếu.
- **Kiểm chứng:** hai snapshots khác nhau, token/context overflow bằng fake tokenizer phù hợp adapter, kiểm tra provenance không mất khi rút gọn.

### P2.4 — Sandbox runner và tool job lifecycle

- **Phụ thuộc:** P2.1–P2.3; runtime container/runner có sẵn cho live check.
- **Thực hiện:** runner profile cho target OS; bản copy snapshot, timeout, quota, network policy, bounded output, process cleanup; structured job status và availability probe.
- **Contract:** JobResult lưu environment/image version, command đã redact, expected/actual, exit code và evidence ref. Trạng thái unavailable/timeout/cancelled khác PASS/FAIL. Không dùng host subprocess như fallback sandbox cho code không tin cậy.
- **Đầu ra:** runner adapter, sandbox profiles, tool-to-evidence integration và ADR-005.
- **Nghiệm thu:** không ghi repo nguồn; không mount API secrets; kill job treo; thiếu runner trả unavailable và validation NOT_RUN. Linux runner không tuyên bố chứng minh hành vi Windows-specific.
- **Kiểm chứng:** fixture pass/fail/hang/large output; kiểm tra mount và cleanup; live sandbox test khi hạ tầng có sẵn.

### P2.5 — Demo khảo sát repo và bàn giao

- **Phụ thuộc:** P2.1–P2.4.
- **Thực hiện:** demo capture → inspect → claim/evidence → verification; tài liệu hóa output contract cho P3.
- **Đầu ra:** CLI/tool demo, evidence index mẫu, snapshot/tool instructions và phase report.
- **Nghiệm thu:** truy ngược từ claim đến nội dung/command trong đúng snapshot; các kiểm chứng chưa chạy được ghi rõ; không làm thay đổi source fixture.
- **Kiểm chứng:** integration scenario repo nhỏ, so sánh source hash trước/sau và evidence coverage.

## 3. Exit gate

- [ ] Git dirty/non-Git snapshot chính xác, immutable và có exclusion manifest.
- [ ] Read/search có scope, provenance và output limits.
- [ ] Evidence/context service bàn giao được cho workflow.
- [ ] Runner có live check phù hợp target đã chọn; nếu thiếu hạ tầng ghi phase BLOCKED cho gate này. P3 có thể phát triển nhánh degraded mode bằng fake/unavailable result nhưng không tính thay live verification.
- [ ] ADR-005 và contracts được cập nhật.

**Bàn giao P3:** SnapshotRef, ToolRequest/Result, EvidenceRef, ContextBundle, availability/error semantics và fixtures. Xem [implementation plan](../IMPLEMENTATION_PLAN.md).
