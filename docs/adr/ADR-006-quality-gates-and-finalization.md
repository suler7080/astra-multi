# ADR-006: Quality Gates, Semantic Review, and Plan Finalization Policy

## Trạng thái
ĐÃ CHẤP THUẬN (04/10/2026)

## Bối cảnh
Astra Multi thiết kế kiến trúc phần mềm với cam kết kiểm chứng chất lượng ở mức cao nhất. Một kế hoạch kiến trúc không thể được công bố ở trạng thái `FINAL` chỉ bằng sự nhất trí chủ quan của các LLM hay đơn thuần vì đã chạy hết số vòng hội thoại. Cần có một chính sách chất lượng xác định (P4 Quality Service) kiểm soát ranh giới giữa bản nháp/bộ phận (`PARTIAL`) và bản hoàn chỉnh (`FINAL`).

## Quyết định kiến trúc

1. **Phân tách ranh giới kiểm định (Structural vs Semantic):**
   - **Structural Quality Validator (P4.1):** Kiểm tra các bất biến cấu trúc bằng mã xác định thuần túy (không qua LLM):
     - Bao phủ 100% yêu cầu (`TaskSpec.requirements`) bởi các bước kế hoạch (`PlanStep`).
     - Đồ thị phụ thuộc bước kế hoạch tạo thành DAG hợp lệ (không chu trình, không phụ thuộc vào ID không tồn tại).
     - Tính toàn vẹn tham chiếu (IDs của requirement, step, decision, evidence, issue).
     - Không còn bất kỳ issue nghiêm trọng nào (`IssueSeverity.BLOCKING`) ở trạng thái chưa giải quyết (`status != RESOLVED`).
     - Invariants của execution: `ValidationStatus.NOT_RUN` không được chứa kết quả thực thi hay mã thoát giả mạo.
   - **Semantic Review (P4.2):** Kiểm tra tính khả thi, tính chặt chẽ của validation, và sự tương xứng của giải pháp trên rubric cụ thể.

2. **Chính sách cấp trạng thái `FINAL`:**
   - Trạng thái `FINAL` được bảo vệ tuyệt đối: Chỉ được cấp bởi tác tử/dịch vụ chất lượng (`P4-quality-service`) sau khi:
     1. `StructuralQualityValidator` trả về `passed = True` (0 vi phạm blocker).
     2. `SemanticReviewAssessment` đạt tiêu chuẩn trên **chính bản revision kế hoạch hiện tại** (đánh giá trên revision cũ bị coi là `stale` và từ chối).
     3. Không còn bất kỳ câu hỏi chặn nào (`Question.blocking == True`) chưa được trả lời.
   - Nếu hết ngân sách hoặc dừng do bế tắc khi còn tồn tại blocker, trạng thái kết thúc bắt buộc là `PARTIAL`, tuyệt đối không tự động bỏ qua blocker để cấp `FINAL`.

3. **Xuất bản đa định dạng bảo toàn ngữ nghĩa (P4.3):**
   - Hai định dạng xuất bản chính thức: JSON chuẩn (Schema v1) và Markdown (theo `PLAN_TEMPLATE.md`).
   - Cả hai định dạng đều được xuất từ cùng một snapshot aggregate trạng thái cố định (`RunState`), không gọi thêm LLM viết lại để tránh hallucination khi render.
   - Nội dung văn bản Markdown được escape an toàn, ngăn chặn việc chèn mã HTML độc hại.

## Hệ quả
- Người dùng và hệ thống có thể tin cậy tuyệt đối vào nhãn `FINAL` của bất kỳ kế hoạch nào được xuất ra.
- Các bản kế hoạch `PARTIAL` chỉ rõ chính xác các điểm thiếu sót, lý do dừng và các hành động tiếp theo cần thực hiện.
