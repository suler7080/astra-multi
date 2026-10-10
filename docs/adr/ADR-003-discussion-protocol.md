# ADR-003: Discussion Protocol, Issue Routing, and Evidence Provenance

## Trạng thái
ĐÃ CHẤP THUẬN (04/10/2026)

## Bối cảnh
Astra Multi thiết kế kiến trúc phần mềm thông qua sự phối hợp của nhiều tác tử (Planner, Reviewer, Synthesizer) dưới sự điều phối xác định (Deterministic Controller) theo P3.3.
Cần có một giao thức thảo luận chuẩn hóa, tránh tranh luận chủ quan vô căn cứ giữa các LLM, bảo đảm:
1. Tính độc lập của phân tích ban đầu (Independent Analysis).
2. Quy tắc định tuyến và giải quyết vấn đề (Issue Routing & Resolution) dựa trên bằng chứng kỹ thuật (Evidence).
3. Đóng vấn đề nghiêm trọng (blocking issue) phải qua kiểm định độc lập trên plan revision mới hoặc khi yêu cầu thay đổi (TaskSpec revision).
4. Vòng lặp hội tụ có giới hạn (bounded loop) và phát hiện đình trệ (stagnation).

## Quyết định kiến trúc

1. **Giao thức 11 pha chuẩn hóa (cập nhật theo ADR-007):**
   `INTAKE` -> `SNAPSHOT` -> `INVESTIGATE` -> `INDEPENDENT_ANALYSIS` -> `PROPOSE` -> `REVIEW` -> `VERIFY` -> `REVISE` -> `SEMANTIC_REVIEW` -> `QUALITY_GATE` -> `EXPORT`.
   - Vòng lặp phản biện/sửa đổi giới hạn: `QUALITY_GATE` -> `PROPOSE` (nếu còn round) hoặc `EXPORT` (FINAL/PARTIAL). Tối đa 2 vòng mặc định.

2. **Cách ly ngữ cảnh (Context Isolation):**
   - Trong pha `INDEPENDENT_ANALYSIS`, Planner và Reviewer chỉ nhận baseline gồm `TaskSpec`, metadata của repo snapshot, repo map và essential sources.
   - Các tác tử không nhìn thấy đầu ra, giả định hay đề xuất của đồng cấp ở vòng độc lập.

3. **Truy vết bằng chứng & Định tuyến Issue:**
   - Mọi issue được Reviewer nêu ra bắt buộc phải có `evidence_ids` hoặc `verification_request`.
   - Bất đồng về mặt dữ kiện kỹ thuật trong pha `REVIEW` được chuyển thành lệnh thực thi công cụ hoặc kiểm chứng sandbox trong pha `VERIFY` để ghi nhận `Evidence` có content hash.
   - `IssueSeverity.BLOCKING` chỉ được giải quyết (`RESOLVED`) khi:
     - Có review độc lập `PASS` trên revision kế hoạch mới hơn, HOẶC
     - Yêu cầu (`TaskSpec`) đã được sửa đổi tương ứng.

4. **Phát hiện đình trệ (Stagnation Detection):**
   - Bộ phát hiện đình trệ (`StagnationDetector`) ghi nhận số lượng issue mở/đã giải quyết, bằng chứng và quyết định qua từng vòng.
   - Nếu qua cửa sổ kiểm tra mà không phát sinh thêm bằng chứng mới hoặc không giải quyết thêm issue nào, luồng điều phối sẽ dừng với lý do `STAGNATION_DETECTED` và xuất kết quả `PARTIAL`.

5. **Quyền hạn của Controller:**
   - Controller dùng mã lệnh xác định (deterministic code), ghi mọi mutation qua lệnh P1 (`CommitPlan`, `AddRecord`, `ChangeIssue`, `TransitionRun`) có lease và revision fencing.
   - Các mô hình/tác tử LLM chỉ trả về cấu trúc dữ liệu (`ProposalOutput`, `ReviewOutput`, `SynthesizerOutput`) theo schema nghiêm ngặt, không có quyền sửa đổi ngân sách hoặc luồng điều phối.

## Hệ quả
- Loại bỏ hoàn toàn ảo giác đồng thuận hoặc tranh luận vòng vo không hồi kết giữa các LLM.
- Toàn bộ đề xuất kế hoạch đều có thể kiểm chứng nguồn gốc (provenance) trực tiếp từ snapshot mã nguồn.
