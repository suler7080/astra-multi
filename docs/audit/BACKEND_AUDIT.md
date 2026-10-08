# Báo cáo Kiểm toán Kiến trúc Backend (Backend Audit Report)

## 1. Tóm tắt điều hành
Hệ thống Astra Multi đang ở trạng thái vượt qua 100% các bài kiểm thử nhưng thực tế vòng lặp đa tác nhân (Multi-Agent Loop) bị hỏng nghiêm trọng ở cấp độ điều khiển luồng và tính toàn vẹn trạng thái. Nguyên nhân gốc rễ khiến run Minesweeper (`RUN-c5039d07`) kết thúc ở `PARTIAL` là do: (1) Đồ thị bị lỗi định tuyến, mũi tên quay về `review` thay vì `propose` khiến Proposal không bao giờ được cập nhật; (2) Thiếu hoàn toàn logic cập nhật trạng thái (`ChangeIssue`), khiến các chặn (blocking issues) không bao giờ được `RESOLVED` qua đánh giá độc lập trên revision mới. Do đó Cổng chất lượng (Gate) từ chối cấp `FINAL`. Ngoài ra, việc dùng `uuid4` phá vỡ idempotency và hệ thống quản lý ngân sách (`budget.py`) bị lỗi thiếu cơ chế retry và không lưu trạng thái vào DB.

## 2. Bảng Invariants

| Invariant | Trạng thái | Bằng chứng / Vị trí |
| :--- | :--- | :--- |
| **Thứ tự 11 pha** | ENFORCED | `domain/policies.py:58` (`PHASE_TRANSITIONS`), `domain/models.py:60` (`RunPhase`) |
| **Terminal immutability** | ENFORCED | `domain/policies.py:175` |
| **FINAL chỉ do P4** | ENFORCED | `domain/policies.py:298` |
| **Issue state machine** | ENFORCED | `domain/policies.py:71` (`ISSUE_TRANSITIONS`) |
| **Điều kiện reviewer độc lập PASS** | ENFORCED | `domain/policies.py:116-129` |
| **Evidence-first** | ENFORCED | `domain/models.py:281` |
| **Context isolation** | ENFORCED | `orchestration/graph.py:117, 148` (Tạo bundle cô lập) |
| **Schema extra=forbid** | ENFORCED | `domain/models.py:45` |
| **Strict DAG** | ENFORCED | `domain/models.py:329-338` |
| **100% requirement coverage** | PARTIAL | Gate kiểm tra (`graph.py:438`) nhưng `propose_node` làm giả dữ liệu (`graph.py:214`) |
| **Zero blockers** | ENFORCED | `orchestration/graph.py:429` |
| **Stagnation** | ENFORCED | `orchestration/graph.py:444` |
| **max_rounds** | ENFORCED | `orchestration/graph.py:448` |
| **Fenced lease** | ENFORCED | `persistence/sqlite.py:283-305` (`acquire`), `258-276` (`_check_lease`), `184-256` (`commit`) (kết luận `BASELINE.md:164-231`) |
| **Expected_revision** | ENFORCED | `domain/policies.py:171-174` |
| **Idempotency** | VIOLATED | Sinh `uuid.uuid4()` trong nội bộ node tại `graph.py:218, 275` |
| **Budget reserve/settle** | VIOLATED | Thiếu logic persist/retry trong `budget.py`, không gọi ở `graph.py` |

## 3. Danh sách phát hiện (Findings)

| ID | Mức độ | File:Line | Invariant | Trạng thái |
| :--- | :--- | :--- | :--- | :--- |
| **F-001** | Critical | `orchestration/graph.py:484, 517` | Thứ tự 11 pha / Stagnation | VERIFIED |
**Mô tả:** Mũi tên từ Gate quay về `review` thay vì `propose`. Kéo theo Proposal không được cập nhật mới ở mỗi vòng, khiến Reviewer và Synthesizer luôn dùng dữ liệu cũ kỹ. (H1 được chứng minh).
**Đề xuất sửa:** Trong `should_loop_or_export`, đổi trả về `"propose"` thay vì `"review"`.
**Công sức (S/M/L):** S. **Test cần thêm:** Test vòng lặp 2 vòng phải có `propose` được gọi 2 lần.

| ID | Mức độ | File:Line | Invariant | Trạng thái |
| :--- | :--- | :--- | :--- | :--- |
| **F-002** | Critical | `orchestration/graph.py:416` (toàn file) | Điều kiện Reviewer độc lập PASS | VERIFIED |
**Mô tả:** Không có đường code nào sử dụng command `ChangeIssue` để chuyển trạng thái Issue. Mọi issue được tạo ra sẽ vĩnh viễn ở trạng thái `OPEN` hoặc block luồng, dẫn đến không thể thỏa mãn invariant `RESOLVED` (đòi hỏi Reviewer độc lập đánh giá PASS). H2 và H5 được chứng minh.
**Đề xuất sửa:** Bổ sung việc LLM (Reviewer) output các `resolutions` cho issue cũ, và node `review_node` thực hiện apply `ChangeIssue`.
**Công sức (S/M/L):** L. **Test cần thêm:** Test Reviewer đóng issue thành công qua `ChangeIssue`.

| ID | Mức độ | File:Line | Invariant | Trạng thái |
| :--- | :--- | :--- | :--- | :--- |
| **F-003** | High | `orchestration/graph.py:214, 346, 359` | 100% Requirement Coverage | VERIFIED |
**Mô tả:** Code chủ động làm giả (spoof) dữ liệu khi LLM bỏ sót. Node `propose` tự động lấy 100 ký tự đầu của approach gán cho coverage nếu rỗng. Node `revise` điền cứng mảng deliverables và criteria. H4 được chứng minh.
**Đề xuất sửa:** Xóa logic spoofing. Để cho `quality_gate_node` chặn nếu schema vi phạm hoặc thiếu coverage, ép LLM sửa lỗi qua vòng lặp.
**Công sức (S/M/L):** S. **Test cần thêm:** Test chặn mảng rỗng và báo lỗi.

| ID | Mức độ | File:Line | Invariant | Trạng thái |
| :--- | :--- | :--- | :--- | :--- |
| **F-004** | High | `orchestration/budget.py:82, 124` | Budget reserve/settle | VERIFIED |
**Mô tả:** Phương thức `reserve` nếu gặp `RevisionConflict` sẽ ném lỗi thay vì retry, làm sập tiến trình. Các phương thức `settle` và `release` thay đổi bộ đếm in-memory nhưng hoàn toàn không gọi `repository.commit` để lưu xuống DB (mất dữ liệu khi restart). `graph.py` cũng không hề gọi `budget_service`. H6 được chứng minh.
**Đề xuất sửa:** Thêm vòng lặp `while True: try/except RevisionConflict` vào `reserve`, `settle`, `release` kèm logic `repository.commit`.
**Công sức (S/M/L):** M. **Test cần thêm:** Test budget chịu được race condition và sống sót qua restart.

| ID | Mức độ | File:Line | Invariant | Trạng thái |
| :--- | :--- | :--- | :--- | :--- |
| **F-005** | Medium | `orchestration/graph.py:218, 275` | Idempotency | VERIFIED |
**Mô tả:** Việc sử dụng `uuid.uuid4().hex` trực tiếp trong LangGraph nodes (vốn có thể bị resume/retry) khiến mỗi lần chạy lại sẽ sinh một ID mới (cho Proposal và Issue), phá vỡ Idempotency. H7 được chứng minh.
**Đề xuất sửa:** Dùng UUID dẫn xuất (deterministic) từ `(run_id, round, node_name, index)` hoặc sử dụng content hash.
**Công sức (S/M/L):** S. **Test cần thêm:** Test `invoke()` graph 2 lần với cùng input không bị nhân bản bản ghi.

| ID | Mức độ | File:Line | Invariant | Trạng thái |
| :--- | :--- | :--- | :--- | :--- |
| **F-006** | Medium | `orchestration/graph.py:265` | Context accuracy | VERIFIED |
**Mô tả:** `review_node` dùng `valid_reqs = {r.id for task in curr_state.tasks for r in task.requirements}`, bao gồm cả yêu cầu từ các version cũ đã bị xóa. H8 được chứng minh.
**Đề xuất sửa:** Đổi thành `curr_state.task.requirements` (bản mới nhất).
**Công sức (S/M/L):** S. **Test cần thêm:** Không yêu cầu trực tiếp.

| ID | Mức độ | File:Line | Invariant | Trạng thái |
| :--- | :--- | :--- | :--- | :--- |
| **F-007** | Medium | `orchestration/graph.py:365-388` | - | VERIFIED |
**Mô tả:** Node `revise_node` luôn tạo Decision mới thay vì cập nhật hay thay thế. Decision cũ không có cơ chế invalidate. H3 được chứng minh.
**Đề xuất sửa:** Bổ sung tính năng supersede hoặc chỉ giữ lại decision hợp lệ với revision hiện tại.
**Công sức (S/M/L):** M. **Test cần thêm:** Test số lượng Decision không bị phình to vô lý.

| ID | Mức độ | File:Line | Invariant | Trạng thái |
| :--- | :--- | :--- | :--- | :--- |
| **F-008** | High | `orchestration/graph.py:423` | Strict DAG / Zero Blockers | VERIFIED |
**Mô tả:** `quality_gate_node` chỉ check list bằng logic thủ công chứ không gọi `StructuralQualityValidator` từ `exports/quality_validator.py`. H2 được chứng minh.
**Đề xuất sửa:** Import và gọi `StructuralQualityValidator` trong `quality_gate_node`.
**Công sức (S/M/L):** S. **Test cần thêm:** Test Gate báo lỗi khi gọi Validator bị lỗi DAG.

## 4. Kế hoạch sửa theo giai đoạn (Staged Fix Plan)

### Giai đoạn 1: Fix luồng đồ thị và loại bỏ Spoofing (Ưu tiên cao nhất)
- **Mục tiêu:** Mở khóa (unblock) vòng lặp hội tụ, đảm bảo Proposal được làm mới và các lỗi thiếu hụt bị bộc lộ.
- **Thay đổi file:**
  - `orchestration/graph.py`: 
    - Cập nhật `should_loop_or_export` để điều hướng về `propose` thay vì `review`.
    - Xóa toàn bộ logic làm giả dữ liệu (spoofing) ở `propose_node` và `revise_node`. Đổi `valid_reqs` ở `review_node` thành `.task.requirements`.
    - Tích hợp `StructuralQualityValidator` vào `quality_gate_node`.
- **Tiêu chí hoàn thành:** Chạy đồ thị với input thiếu sót sẽ thấy bị chặn lại ở Gate, đồ thị quay lại đúng `propose_node`, và không có dữ liệu rác nào tự sinh.

### Giai đoạn 2: Sửa cơ chế Idempotency và Review Cập nhật (Issue Resolution)
- **Mục tiêu:** Đảm bảo hệ thống có thể recover an toàn và Reviewer có thể đánh giá `PASS` cho các issue đã sửa để vượt qua Gate.
- **Thay đổi file:**
  - `orchestration/graph.py`: Đổi `uuid4()` thành hàm sinh ID tĩnh theo round.
  - Sửa `ReviewOutput` (trong `roles.py`) bổ sung mảng `resolutions` để cập nhật status của issue.
  - `orchestration/graph.py`: Tại `review_node`, lặp qua `review_out.resolutions` và gọi `ctrl.repository.commit(ChangeIssue(...))` để đóng issue.
- **Tiêu chí hoàn thành:** Run Minesweeper có thể chạy thành công ra `FINAL` thay vì kẹt ở `PARTIAL`.

### Giai đoạn 3: Vá lõi Ngân sách (Budget Service Durability)
- **Mục tiêu:** Quản lý ngân sách an toàn đồng thời, không mất dữ liệu khi ứng dụng sập.
- **Thay đổi file:** 
  - `orchestration/budget.py`: Bọc `self.repository.commit(...)` trong vòng lặp `try...except RevisionConflict` khi `reserve`. Bổ sung commit DB cho `settle` và `release`.
  - `orchestration/graph.py`: Gọi `budget_service.reserve()` trước mỗi lần gọi model và `budget_service.settle()` / `release()` sau khi có kết quả.
- **Tiêu chí hoàn thành:** Restart server đang chạy giữa chừng không bị reset budget (cost và token). Test gọi đồng thời 10 threads `reserve` đều thành công.

## 5. Các điểm cần con người quyết định (ADR cần viết)

- **CẦN ADR: Về Invariant Điều kiện Reviewer Độc lập (P4 Quality Gate)**
  - **Vấn đề:** Hiện tại vòng lặp chạy đến `REVISE` là ra `QUALITY_GATE`. Nhưng để một blocking issue thỏa mãn được trạng thái `RESOLVED`, Reviewer cần đánh giá `PASS` trên revision của plan mới nhất (tức là plan vừa được sinh ra ở phase REVISE đó). Nếu Gate kiểm tra ngay, issue sẽ luôn bị coi là chưa giải quyết (vì thiếu lượt Review đánh giá bản Plan mới).
  - **Phương án không đổi invariant:** Sửa đổi kiến trúc đồ thị LangGraph. Hoặc thêm pha `SEMANTIC_REVIEW` chèn giữa `REVISE` và `QUALITY_GATE` để tác nhân Reviewer có cơ hội đọc Plan mới và phê duyệt; Hoặc thay đổi mũi tên quy trình: `REVISE` sinh plan mới -> tự động chuyển về `REVIEW` đọc lại -> nếu Reviewer pass hết thì mới đi tiếp sang `GATE`.
  - Cần kiến trúc sư quyết định cấu trúc vòng lặp nào tối ưu hơn và viết ADR.

## 6. Mục tối ưu (Cost / Tokens / Performance)

- **Performance trong `budget.py`**: Hiện tượng lặp qua toàn bộ dict `self._reservations` mỗi lần gọi `reserve` tốn kém $O(N)$. Có thể duy trì 2 biến đếm `_reserved_tokens` và `_reserved_cost` cập nhật tại chỗ khi reserve, settle, release để tối ưu hóa thời gian tính toán.
- **Tối ưu chi phí Token (Prompt Bloat)**: Kích thước prompt phình to theo từng vòng lặp (vì lịch sử model_calls và events giữ nguyên). Cần có cơ chế cắt xén (truncate) hoặc tóm tắt history cho các tác nhân ở vòng sau (đặc biệt là Planner và Reviewer) để tránh vượt quá context window và giảm chi phí tiền tệ.

*(Lưu ý: Báo cáo này không bao gồm kiểm tra chi tiết lỗi Race Condition thực tế trong SQLite do giới hạn đọc mã, nhưng logic khoá Epoch và Fenced Lease đã được ghi nhận `ENFORCED` dựa trên tài liệu kiến trúc và code policies).*
