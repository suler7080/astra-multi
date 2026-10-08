# Bộ prompt P5 - Củng cố sau khi sửa F-001..F-008

Thứ tự chạy: P5.0 -> P5.1 -> P5.2 -> P5.3 -> P5.4 -> V2 (verifier mới, agent mới).
Mỗi prompt bắt đầu bằng đoạn "Prompt dùng chung" trong AGENT_PROMPTS.md, cộng thêm quy tắc P5 dưới đây.

---

## Quy tắc bổ sung cho P5 (dán sau Prompt dùng chung)

```
Bối cảnh: F-001..F-008 đã sửa, VERIFY.md báo PASS, 386 test xanh. Đồ thị hiện có
pha SEMANTIC_REVIEW giữa REVISE và QUALITY_GATE (ADR phương án A).
Không tin VERIFY.md một cách mù quáng: kiểm tra lại bằng code và lệnh thật.
Mọi số liệu trong báo cáo của bạn phải đến từ lệnh bạn đã chạy, ghi rõ lệnh đó.
Không dùng LLM thật nếu không có biến môi trường ASTRA_LIVE_LLM=1 và trần ngân sách
được đặt (xem P5.1).
```

---

## P5.0 - Đồng bộ ADR và tài liệu invariant (không đổi logic)

```
[Prompt dùng chung] [Quy tắc P5]

Phạm vi: tài liệu + một test cấu trúc. Không sửa logic orchestration.
1. Mở domain/policies.py (PHASE_TRANSITIONS) và liệt kê đúng danh sách pha hiện tại
   và số pha. So sánh với mọi nơi còn ghi "10 pha" (docs, comment, test, README,
   BACKEND_AUDIT.md, tên hằng số).
2. Tạo/cập nhật docs/adr/00X-semantic-review-phase.md: bối cảnh, quyết định
   (phương án A), phương án đã loại (B) và lý do, hệ quả lên invariant.
   Nếu file ADR đã có, đối chiếu nội dung với code và sửa chỗ sai.
3. Cập nhật bảng invariant: "Thứ tự N pha" đúng số thật, "Fenced lease" đúng kết quả
   mà BASELINE.md đã kết luận (nếu BASELINE.md không có kết luận, tự kiểm tra
   repository/sqlite.py và ghi bằng chứng file:line).
4. Thêm 1 test khẳng định: tập pha trong PHASE_TRANSITIONS khớp một hằng số
   EXPECTED_PHASES duy nhất, để lần sau đổi pha mà quên tài liệu sẽ fail.
Báo cáo: danh sách chỗ lệch đã sửa.
```

---

## P5.1 - Run bằng model thật, có trần ngân sách (chỉ quan sát, không sửa)

```
[Prompt dùng chung] [Quy tắc P5]

Mục tiêu: kiểm tra giả định "reviewer trả resolutions đúng định dạng" với LLM thật.
Không sửa code trong bước này.
1. Viết script scripts/live_minesweeper_run.py chạy đúng fixture Minesweeper với
   model thật. Bắt buộc: đọc ASTRA_LIVE_LLM=1, đặt trần cứng tổng chi phí (mặc định
   1.00 USD) thông qua budget service, dừng ngay khi chạm trần. Thiếu biến môi
   trường hoặc API key thì in hướng dẫn và thoát, không chạy.
2. Chạy tối đa 3 lần độc lập. Với mỗi lần ghi: trạng thái cuối (FINAL/PARTIAL/FAILED),
   số vòng, mỗi issue blocking có được RESOLVED không, lần nào reviewer trả
   resolutions sai schema (và sai thế nào), tổng token và chi phí thực tế so với
   mức reserve 4.000 token.
3. Ghi LIVE_RUN.md với bảng kết quả 3 lần chạy và các lỗi gặp phải.
4. Với mỗi lỗi lặp lại >= 2 lần, đề xuất fix (không tự áp dụng).
Nếu không có API key, dừng sau bước 1 và báo cáo là chưa chạy được.
```

---

## P5.2 - ID tất định theo nội dung + reservation theo độ dài prompt

```
[Prompt dùng chung] [Quy tắc P5]

Đọc LIVE_RUN.md nếu có, xử lý ưu tiên các lỗi đã ghi ở đó, rồi:

A. Issue ID (rủi ro: cùng (run_id, round, node, idx) nhưng nội dung khác sau retry
   thì trùng ID):
   - Dẫn xuất ID Issue từ (run_id, round, node, hash chuẩn hóa của nội dung issue).
     Chuẩn hóa: strip, gộp khoảng trắng, lowercase các trường định danh.
   - Giữ nguyên cách dẫn xuất cho Proposal nếu không có rủi ro tương tự, và giải thích.
   - Test: retry cùng nội dung -> cùng ID, không nhân bản; nội dung khác ở cùng vị trí
     -> ID khác, không ghi đè nhau.

B. Reservation ngân sách:
   - Thay hằng 4.000 token trong _call_model_with_budget bằng ước lượng
     (độ dài prompt đã chuẩn bị + max output tokens của lời gọi) nhân hệ số an toàn
     cấu hình được. Dùng tokenizer sẵn có của dự án, nếu không có thì ước lượng
     theo ký tự và ghi rõ giả định.
   - Nếu ước lượng vượt ngân sách còn lại, từ chối trước khi gọi model, không gọi rồi mới biết.
   - Test: prompt lớn (> 4.000 token) reserve đúng lớn hơn mức cũ; settle sau
     khi lỗi vẫn release đúng; tổng reserved không vượt ngân sách.

C. Migration F-007 (supersede Decision):
   - Tạo fixture dữ liệu run CŨ (trước supersede) và test: đọc, resume và export
     run cũ không lỗi. Nếu lỗi, thêm bước tương thích đọc (không sửa dữ liệu cũ tại chỗ).
```

---

## P5.3 - Stagnation / max_rounds trên đồ thị 11 pha

```
[Prompt dùng chung] [Quy tắc P5]

Phạm vi: kiểm chứng và vá nếu cần việc đếm vòng sau khi thêm SEMANTIC_REVIEW.
1. Đọc cách orchestration/graph.py tính round và phát hiện stagnation
   (khoảng sau dòng 444-448 trước đây; mở code thật).
2. Viết test với LLM giả cho 4 kịch bản:
   a. Blocker không bao giờ được giải quyết -> dừng đúng ở max_rounds, trạng thái cuối PARTIAL.
   b. Hai vòng liên tiếp cùng tập blocker -> kích hoạt stagnation đúng, không đợi tới max_rounds.
   c. Blocker được giải quyết ở vòng cuối cùng được phép -> FINAL, không bị cắt sớm.
   d. SEMANTIC_REVIEW không làm tăng round thêm một lần (đếm round theo vòng lặp, không theo số node).
3. Nếu test nào fail, sửa tối thiểu trong graph.py, mỗi sửa kèm test fail-trước.
Báo cáo: kịch bản nào lệch, đã sửa gì.
```

---

## P5.4 - Prompt bloat (Mục 6 của audit)

```
[Prompt dùng chung] [Quy tắc P5]

Mục tiêu: giảm kích thước prompt ở vòng sau mà không làm mất thông tin mà invariant cần.
1. Đo trước: viết test/script ghi số token của prompt từng tác nhân (Planner, Reviewer,
   Synthesizer) qua 5 vòng với fixture Minesweeper kéo dài. Lưu số liệu BEFORE.
2. Thiết kế context bundle theo vòng: giữ nguyên toàn bộ (a) plan và proposal hiện tại,
   (b) mọi issue chưa RESOLVED, (c) resolution gần nhất của mỗi issue đã đóng.
   Cắt/tóm tắt: lịch sử model_calls và events của các vòng cũ (giữ N vòng gần nhất
   ở dạng đầy đủ, N cấu hình được; các vòng cũ hơn chỉ còn bản tóm tắt tất định
   dạng bảng đếm/sự kiện chính, KHÔNG tóm tắt bằng LLM).
3. Không được phá context isolation (orchestration/graph.py khoảng 117, 148): tác
   nhân vẫn chỉ nhận bundle cô lập của riêng nó.
4. Test: (i) token prompt vòng 5 giảm có ý nghĩa so với BEFORE (ghi số cụ thể),
   (ii) kết quả Minesweeper vẫn FINAL, (iii) issue chưa RESOLVED luôn có trong
   prompt Reviewer ở mọi vòng.
Lưu số liệu AFTER và so sánh trong báo cáo. Không đặt ngưỡng "giảm X%" nếu số đo không chứng minh.
```

---

## V2 - Verifier độc lập vòng 2 (agent mới)

```
Bạn là reviewer độc lập, không sửa code. Không đọc báo cáo tự đánh giá của các agent
trước trước khi tự kiểm tra, chỉ đọc sau để đối chiếu.
Kiểm tra bằng lệnh thật:
1. Full test suite: số pass/fail/skip, so với 386 passed / 13 skipped trước P5.
2. Với P5.0..P5.4: xác nhận từng test mới fail khi revert phần sửa tương ứng
   (git stash có chọn lọc), ghi lệnh và kết quả.
3. Không có test bị xóa, làm yếu, skip/xfail mới; không còn uuid4 trong graph nodes.
4. Test tài liệu-khớp-code (P5.0) fail được nếu sửa PHASE_TRANSITIONS giả.
5. Số đo token BEFORE/AFTER của P5.4 được tái hiện lại, không chỉ trích dẫn.
6. Nếu có LIVE_RUN.md: xác nhận ít nhất một run FINAL với model thật, hoặc ghi
   rõ chưa có bằng chứng.
Xuất VERIFY_2.md: bảng hạng mục -> PASS/FAIL/KHÔNG KIỂM CHỨNG ĐƯỢC + bằng chứng.
Phần "không kiểm chứng được" phải được liệt kê riêng, không gộp vào PASS.
```

---

## Ghi chú vận hành

- P5.1 tốn tiền thật: kiểm tra trần ngân sách trước khi chạy.
- Nếu P5.1 không chạy được (thiếu key), P5.2 vẫn làm được nhưng bỏ phần ưu tiên theo lỗi live.
- Nên chạy cả bộ trên CI Linux để mở lại 13 test đang skip.
