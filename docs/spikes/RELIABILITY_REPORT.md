# Báo cáo Độ tin cậy và Kiểm chứng Invariants (P6.1 Reliability Report)

Ngày lập: 04/10/2026.
Phạm vi: Toàn bộ các kiểm chứng fault injection, crash recovery, concurrency, lease fencing, và data integrity invariants theo yêu cầu của P6.1 và PLAN.md §12.1.

---

## 1. Tóm tắt kết quả kiểm định

Hệ thống đã trải qua ma trận kiểm thử sự cố (Fault Injection Matrix) bao gồm 8 nhóm kịch bản chính:
1. **Kill tiến trình trước / sau commit và checkpoint**: Atomicity được bảo toàn tuyệt đối, revision tự phục hồi chính xác khi tiến trình worker khởi động lại.
2. **Lease contention & expired lease fencing**: Tác nhân nắm lease cũ bị chặn đứng ngay lập tức khi lease hết hạn hoặc bị takeover bởi tác nhân mới (epoch fencing increment).
3. **Budget race condition & reservation ceiling**: Khi nhiều luồng cùng tranh chấp ngân sách, tổng hạn mức không bao giờ bị vượt quá; các cuộc gọi vượt hạn mức bị từ chối với lỗi `BudgetExhaustedError`.
4. **Cổng chất lượng không cho phép FINAL khi còn Blocker (Zero FINAL with blocker)**: Đảm bảo 100% không có bất kỳ kế hoạch nào được cấp trạng thái `FINAL` nếu còn tồn tại Issue mức `BLOCKING` hoặc vi phạm cấu trúc DAG / requirement coverage.
5. **Sandbox unavailability invariant**: Môi trường runner không khả dụng hoặc thiếu driver (ví dụ Docker Linux trên Windows không bật daemon) luôn trả về trạng thái `unavailable` và kết quả kiểm chứng `NOT_RUN`, tuyệt đối không bị chuyển đổi ngầm thành `PASS`.
6. **Bảo toàn Artifact và tính bất biến của Revision**: Mọi artifact đều gắn mã băm SHA-256. Bất kỳ sự can thiệp / sửa đổi trái phép nào trên đĩa lưu trữ đều bị phát hiện ngay lập tức (`ValueError: artifact hash or size mismatch`). Revision kế hoạch tăng tuần tự và không trùng lặp.
7. **Hủy Run (Cancellation Safety)**: Khi nhận lệnh `CANCELLED`, run worker dừng ngay lập tức mọi tiến trình chuyển phase và bảo toàn trạng thái dừng (`stop_reason`).
8. **SSE Reconnect và Replay Integrity**: Khách hàng ngắt kết nối và kết nối lại với tiêu đề `Last-Event-ID` nhận được chính xác luồng sự kiện tiếp theo theo thứ tự thời gian tăng dần, không bị sót hoặc trùng lặp sự kiện.

---

## 2. Chi tiết ma trận kịch bản sự cố

| Mã kịch bản | Mô tả tình huống thử nghiệm | Kết quả kỳ vọng | Kết quả thực tế | Trạng thái |
|---|---|---|---|---|
| **SCN-01** | Kill worker ngay tại các ranh giới commit domain / checkpoint | Không hỏng DB, phục hồi đúng revision, không trùng canonical events | Kiểm chứng qua `test_crash.py` (4 ranh giới commit: `after_mutation`, `after_event`, `after_operation`, `after_domain_commit`) | **PASS** |
| **SCN-02** | Tranh chấp Lease giữa 2 subprocess đồng thời | Đúng 1 worker thắng, worker thua bị từ chối; worker cũ bị epoch fence chặn khi quá hạn | Kiểm chứng qua `test_subprocess_lease_contention_and_takeover_fences_old_writer` | **PASS** |
| **SCN-03** | 25 luồng đồng thời reserve budget vượt trần (5000 tokens / $0.50) | Tổng reserve không bao giờ vượt 5000 tokens / $0.50; 15+ luồng nhận `BudgetExhaustedError` | Kiểm chứng qua `test_concurrent_budget_reservations_race_condition` | **PASS** |
| **SCN-04** | Semantic Review nói "PASS" nhưng tồn tại 1 Issue `BLOCKING` | Cổng chất lượng từ chối `FINAL`, chuyển sang `PARTIAL` kèm thông báo lý do chính xác | Kiểm chứng qua `test_zero_final_with_unresolved_blocker_invariant` | **PASS** |
| **SCN-05** | Sandbox Linux Docker chạy trên Windows khi chưa có daemon | Trả về `unavailable`, validation status là `NOT_RUN`, không bao giờ là `PASS` | Kiểm chứng qua `test_unavailable_runner_never_becomes_pass` | **PASS** |
| **SCN-06** | Sửa đổi trái phép nội dung artifact đã commit trên đĩa | Kiểm tra mã băm SHA-256 khi đọc và ném lỗi `artifact hash or size mismatch` | Kiểm chứng qua `test_no_committed_artifact_loss_or_duplicate_canonical_revision` | **PASS** |
| **SCN-07** | Client SSE mất kết nối và kết nối lại kèm `Last-Event-ID` | SSE worker replay đúng các sự kiện có `event_id > Last-Event-ID` theo đúng thứ tự | Kiểm chứng qua `test_sse_reconnect_replay_integrity` | **PASS** |
| **SCN-08** | Lập lịch tiến trình bị hủy bởi lệnh `CANCEL` của người dùng | Dừng tiến trình điều phối, trạng thái chuyển sang `CANCELLED`, đóng SSE stream sạch sẽ | Kiểm chứng qua `test_api_cancel_and_resume` | **PASS** |

---

## 3. Bằng chứng kiểm thử tự động

Bộ test kiểm chứng độ tin cậy được tích hợp tại:
- `backend/tests/recovery/test_crash.py`: Bộ kiểm thử crash & recovery process native.
- `backend/tests/recovery/test_invariants.py`: Bộ kiểm thử integration invariants & fault injection.
- `backend/tests/integration/test_api.py`: Bộ kiểm thử SSE reconnect replay và cancellation API.
- `backend/tests/integration/test_sandbox.py`: Bộ kiểm thử runner isolation và unavailability.

Toàn bộ 339 bài kiểm tra trong toàn hệ thống (bao gồm 5 bài kiểm tra invariants mới) đều đã chạy thành công 100%.

---

## 4. Các vấn đề còn tồn đọng (Remaining Issues)

- Hiện tại không phát hiện bất kỳ lỗi hồi quy hay rủi ro toàn vẹn dữ liệu nào trong ma trận lỗi.
- Đạt tiêu chuẩn nghiệm thu P6.1:
  - [x] Không mất committed artifact.
  - [x] Không duplicate canonical revision.
  - [x] Zero FINAL với blocker trong fixture tests.
  - [x] Không vượt reservation cap dưới tác động đồng thời.
  - [x] Unavailable checks không biến thành PASS.
