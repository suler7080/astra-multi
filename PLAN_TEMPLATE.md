# [Tên nhiệm vụ] — Kế hoạch triển khai

## 1. Thông tin bản kế hoạch

- Run ID:
- Plan revision:
- TaskSpec revision:
- Snapshot ID / manifest hash:
- Trạng thái: FINAL / PARTIAL / WAITING_FOR_INPUT
- Lý do trạng thái:
- Ngày tạo:

## 2. Mục tiêu và phạm vi

### Mục tiêu

[Kết quả cần đạt và người sử dụng.]

### Trong phạm vi

- ...

### Ngoài phạm vi

- ...

### Yêu cầu và tiêu chí chấp nhận

| Requirement ID | Yêu cầu | Tiêu chí chấp nhận |
|---|---|---|
| REQ-001 | ... | ... |

## 3. Dữ kiện, giả định và câu hỏi

| Claim ID | Loại: fact/assumption/unknown | Nội dung | Evidence ID | Ảnh hưởng nếu sai |
|---|---|---|---|---|
| CLM-001 | ... | ... | ... | ... |

Không biết vị trí code chính xác thì ghi cần khảo sát, không tạo đường dẫn giả.

## 4. Phương án kiến trúc

### Phương án được chọn

[Thành phần, luồng dữ liệu, interface, thay đổi chính.]

### Quyết định và trade-off

| Decision ID | Vấn đề | Lựa chọn | Alternative đáng cân nhắc | Lý do và bằng chứng |
|---|---|---|---|---|
| DEC-001 | ... | ... | ... | ... |

## 5. Các bước thực hiện

### STEP-001 — [Tên bước]

- **Mục tiêu:**
- **Requirements:** REQ-...
- **Module/file/interface tác động:**
- **Phụ thuộc:** không có / STEP-...
- **Thay đổi cần thực hiện:**
- **Đầu ra bàn giao:**
- **Cách xác minh:** lệnh/check cụ thể và kết quả mong đợi; hoặc task khám phá nếu lệnh chưa xác định.
- **Tiêu chí hoàn thành:**
- **Rủi ro / cách xử lý:**

### Thứ tự và song song

[Liệt kê dependency DAG; các bước cùng ghi một interface/file cần phối hợp.]

## 6. Ma trận bao phủ

| Requirement | Step | Validation ID | Kết quả mong đợi |
|---|---|---|---|
| REQ-001 | STEP-001 | VAL-001 | ... |

## 7. Chiến lược kiểm chứng

| Validation ID | Kiểm tra | Môi trường | Expected | Trạng thái NOT_RUN/PASS/FAIL | Evidence nếu đã chạy |
|---|---|---|---|---|---|
| VAL-001 | ... | ... | ... | NOT_RUN | ... |

Phân biệt kiểm chứng đã làm trong lúc lập plan với test dự kiến sau implementation.

## 8. Migration, triển khai và rollback

[Ghi khi liên quan đến dữ liệu hoặc vận hành. Nếu không áp dụng, nêu lý do ngắn.]

## 9. Issues, rủi ro và câu hỏi còn mở

| ID | Nội dung | Mức độ | Trạng thái | Resolution / hành động tiếp |
|---|---|---|---|---|
| ISSUE-001 | ... | ... | ... | ... |

Nếu còn blocker: trạng thái không được là FINAL. Chỉ ra chính xác câu trả lời hoặc bằng chứng cần bổ sung để tiếp tục.

## 10. Evidence index

| Evidence ID | Nguồn / locator | Snapshot / hash | Nội dung chứng minh | Giới hạn |
|---|---|---|---|---|
| EVD-001 | ... | ... | ... | ... |

## 11. Tóm tắt bàn giao

- Bắt đầu từ:
- Thứ tự ưu tiên:
- Điều kiện phải dừng để hỏi thêm:
- Tổng usage và chi phí thực tế/ước tính:
- Liên kết decision log và plan revision trước:
