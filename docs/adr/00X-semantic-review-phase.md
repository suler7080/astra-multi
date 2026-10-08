# ADR-007 (00X): Semantic Review Phase & Blocking Issue Resolution Architecture

**Trạng thái:** ACCEPTED / ĐÃ CHẤP THUẬN (Phương án A)  
**Ngày quyết định:** 07/10/2026 (Triển khai trong bản vá F-002, kiểm chứng tại P5.0)  
**Ngữ cảnh:** BACKEND_AUDIT.md Finding F-002, Invariant "FINAL chỉ do P4" ([domain/policies.py:298](file:///d:/Astra%20multi/backend/src/astra_multi/domain/policies.py#L298)), và Invariant "Điều kiện Reviewer độc lập PASS" ([domain/policies.py:116-129](file:///d:/Astra%20multi/backend/src/astra_multi/domain/policies.py#L116-L129)).

---

## 1. Vấn đề Kiến trúc cốt lõi (Problem Statement)

Hệ thống Astra Multi thiết kế với cam kết kiểm chứng chất lượng ở mức cao nhất: một bản kế hoạch kiến trúc chỉ được cấp trạng thái `FINAL` khi:
1. `StructuralQualityValidator` (P4.1) đạt `passed = True` (0 vi phạm blocker).
2. Toàn bộ các vấn đề nghiêm trọng (`IssueSeverity.BLOCKING`) đều đã được giải quyết (`status == IssueStatus.RESOLVED`).
3. Theo chính sách [domain/policies.py:116-129](file:///d:/Astra%20multi/backend/src/astra_multi/domain/policies.py#L116-L129), một blocking issue chỉ được phép chuyển sang `RESOLVED` khi có một tác nhân **Reviewer độc lập (P4)** đánh giá `PASS` trên **chính bản Plan Revision mới hơn** (`reviewed_revision == state.plan.revision > issue.based_on_revision`).

### Điểm nghẽn trong luồng ban đầu (10 pha):
- Luồng đồ thị 10 pha ban đầu: `PROPOSE → REVIEW → VERIFY → REVISE → QUALITY_GATE`.
- Tại pha `REVISE`, Synthesizer sinh ra bản kế hoạch sửa đổi mới (`PlanRevision` revision $N$).
- Tuy nhiên, ngay sau đó luồng chuyển thẳng sang `QUALITY_GATE`.
- Tại `QUALITY_GATE`, vì chưa hề có bất kỳ lượt đánh giá nào của Reviewer độc lập trên bản Revision $N$ vừa sinh ra, mọi blocking issue vẫn giữ nguyên trạng thái `OPEN`.
- **Hậu quả (F-002):** Quality Gate luôn luôn từ chối (`gate_passed = False`). Khi chạm giới hạn số vòng (`max_rounds`), run (ví dụ run Minesweeper) bị buộc dừng ở trạng thái `PARTIAL`, không bao giờ hội tụ được sang `FINAL`.

---

## 2. Quyết định Kiến trúc: Chọn Phương án A (Thêm pha `SEMANTIC_REVIEW`)

### 2.1. Luồng đồ thị chính thức (11 pha):
```text
INTAKE → SNAPSHOT → INVESTIGATE → INDEPENDENT_ANALYSIS → PROPOSE → REVIEW → VERIFY → REVISE 
  → SEMANTIC_REVIEW → QUALITY_GATE ──┬──► EXPORT (FINAL, nếu đạt)
                                      │
                                      └──► PROPOSE (nếu fail & còn round)
```

### 2.2. Chi tiết thực thi trong mã nguồn:
1. **Enum `RunPhase`** ([backend/src/astra_multi/domain/models.py:69](file:///d:/Astra%20multi/backend/src/astra_multi/domain/models.py#L69)):
   Bổ sung giá trị `SEMANTIC_REVIEW = "SEMANTIC_REVIEW"` (lưu ý: chuỗi viết hoa khớp chuẩn quy ước enum hệ thống).
2. **Chính sách chuyển pha `PHASE_TRANSITIONS`** ([backend/src/astra_multi/domain/policies.py:66-68](file:///d:/Astra%20multi/backend/src/astra_multi/domain/policies.py#L66-L68)):
   ```python
   RunPhase.REVISE: frozenset({RunPhase.QUALITY_GATE, RunPhase.SEMANTIC_REVIEW}),
   RunPhase.SEMANTIC_REVIEW: frozenset({RunPhase.QUALITY_GATE}),
   RunPhase.QUALITY_GATE: frozenset({RunPhase.REVIEW, RunPhase.EXPORT, RunPhase.PROPOSE}),
   ```
   *(Pha `REVISE` hỗ trợ cả `QUALITY_GATE` và `SEMANTIC_REVIEW` để bảo đảm tương thích lùi).*
3. **Node `semantic_review_node` trong LangGraph** ([backend/src/astra_multi/orchestration/graph.py:489-580](file:///d:/Astra%20multi/backend/src/astra_multi/orchestration/graph.py#L489-L580)):
   - Được định tuyến nằm ngay giữa `revise` và `gate`:
     ```python
     graph.add_edge("revise", "semantic_review")
     graph.add_edge("semantic_review", "gate")
     ```
   - Tác nhân Reviewer độc lập (P4) trong node này nhận context bundle cô lập gồm `TaskSpec`, bản `PlanRevision` mới nhất từ `REVISE`, và danh sách các issue mở (`open_issues`).
   - Gọi model với schema phản hồi gồm `resolutions: list[IssueResolutionReport]` và `issues: list[IssueReport]`.
   - Controller áp dụng lệnh `ChangeIssue` hợp lệ theo `ISSUE_TRANSITIONS` để chuyển các issue đạt yêu cầu thành `RESOLVED`.
   - Nếu phát hiện issue mới trong quá trình nghiệm thu, sinh `Issue` với ID tất định `uuid.uuid5` theo format `ISSUE-{run_id}:{round}:semantic_review:{idx}`.
   - Ghi nhận trạng thái round vào `StagnationDetector`.

---

## 3. Phương án đã loại bỏ: Phương án B (`REVISE → REVIEW` lại) và Lý do

### Đề xuất của Phương án B:
Giữ nguyên 10 enum values của `RunPhase`. Đổi routing LangGraph để `revise` nối cạnh quay lại `review`. Node `review_node` hoạt động ở chế độ kép (dual-mode): vừa phát hiện issue mới sau `propose`, vừa nghiệm thu plan mới sau `revise`.

### Lý do loại bỏ Phương án B:
1. **Quá tải vai trò tác tử và Prompt (Role & Prompt Overload):**
   Một node duy nhất phải xử lý hai mục tiêu đối lập: tìm lỗi sơ khởi trên proposal phác thảo và thẩm định nghiệm thu plan chi tiết. Việc gộp chung khiến prompt phức tạp, dễ gây nhầm lẫn context và sinh ảo giác (hallucination).
2. **Phá vỡ nguyên tắc Cổng kiểm soát đơn nhất (Single Gate Control):**
   Nếu rẽ nhánh ngay tại `review` để quay lại `propose` khi còn blocker, luồng sẽ bỏ qua `QUALITY_GATE`. Điều này phân tán quyền điều phối sang hai nơi (Split-brain Routing).
3. **Nguy cơ Vòng lặp Vô tận (Infinite Loop Risk):**
   Vì các chốt chặn an toàn `max_rounds` và `StagnationDetector` được bố trí tại `QUALITY_GATE`, việc rẽ nhánh từ `review` mà bỏ qua `gate` sẽ làm vô hiệu hóa các chốt chặn này, dẫn đến nguy cơ kẹt vòng lặp vô tận.
4. **Phá vỡ tính tinh gọn của chính sách chuyển pha:**
   Đòi hỏi nới lỏng nhiều chuyển pha chéo trong `PHASE_TRANSITIONS` (`REVISE → REVIEW`, `REVIEW → QUALITY_GATE`, `REVIEW → PROPOSE`), làm suy yếu tính kiểm soát của state machine.

---

## 4. Hệ quả lên các Invariant Hệ thống

1. **Invariant "Thứ tự 10 pha" $\rightarrow$ Nâng cấp thành "Thứ tự 11 pha":**
   - Đồ thị chính thức bao gồm 11 pha xác định:
     `INTAKE → SNAPSHOT → INVESTIGATE → INDEPENDENT_ANALYSIS → PROPOSE → REVIEW → VERIFY → REVISE → SEMANTIC_REVIEW → QUALITY_GATE → EXPORT`.
   - Khẳng định tính bất biến này qua test cấu trúc `test_phase_transitions_match_expected_phases` đối soát trực tiếp `PHASE_TRANSITIONS` với hằng số `EXPECTED_PHASES` (11 pha).
2. **Invariant "Điều kiện Reviewer độc lập PASS":**
   - Được khôi phục và bảo toàn 100%: Reviewer độc lập tại `SEMANTIC_REVIEW` nghiệm thu trực tiếp `PlanRevision` mới nhất trước khi chuyển vào `QUALITY_GATE`.
3. **Invariant "Single Control Gate":**
   - Được bảo toàn tuyệt đối: `QUALITY_GATE` là điểm rẽ nhánh duy nhất quyết định lặp lại (`propose`) hay hoàn tất (`export`).
