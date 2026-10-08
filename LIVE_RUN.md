# Báo Cáo Chạy Kiểm Thử Live LLM (LIVE_RUN.md)

**Thời điểm:** 2026-10-08  
**Trạng thái:** DỪNG SAU BƯỚC 1 (Chưa chạy được do thiếu API Key theo quy định P5.1)  

---

## 1. Kết Quả Thực Hiện Bước 1 (Script & Hard Budget Cap)

Đã hoàn thành viết script [`scripts/live_minesweeper_run.py`](file:///d:/Astra%20multi/scripts/live_minesweeper_run.py) đáp ứng đầy đủ yêu cầu:
1. **Kiểm tra điều kiện môi trường bắt buộc:**
   - Yêu cầu `ASTRA_LIVE_LLM=1`. Nếu thiếu, script in hướng dẫn chi tiết và thoát an toàn (mã thoát 1), không gọi LLM.
   - Kiểm tra khóa API hợp lệ từ biến môi trường (`OPENAI_API_KEY`, `GOOGLE_API_KEY`, `XKIRO_API_KEY`) hoặc Windows Credential Manager (`OSCredentialStore`). Nếu không có khóa nào, script in hướng dẫn và thoát ngay lập tức.
2. **Trần ngân sách cứng (Hard Budget Cap):**
   - Thiết lập trần cứng chi phí mặc định **1.00 USD** (hoặc tùy chỉnh qua `--budget-cap` / `ASTRA_BUDGET_CAP_USD`) thông qua [`BudgetService`](file:///d:/Astra%20multi/backend/src/astra_multi/orchestration/budget.py#L41).
   - Khi chạm hoặc vượt ngưỡng chi phí dự phóng, `BudgetService.reserve()` ném ngoại lệ `BudgetExhaustedError` và dừng tiến trình ngay lập tức.
3. **Mô phỏng độc lập Fixture Minesweeper:**
   - Cấu hình TaskSpec chuẩn Greenfield gồm 2 yêu cầu:
     - `REQ-001`: Khởi tạo bảng 9x9 với trạng thái ô (`Grid allocation`).
     - `REQ-002`: Phân bổ mìn với seed PRNG tất định (`Mine distribution`).
   - Tích hợp đồ thị 11 pha đầy đủ, bao gồm pha `SEMANTIC_REVIEW`.
   - Ghi nhận chi tiết: số vòng lặp, trạng thái đóng blocking issue, lỗi vi phạm schema của Reviewer, tổng số token và chi phí thực tế so với mức dự trù cố định 4.000 tokens.

---

## 2. Bằng Chứng Kiểm Tra Bằng Lệnh Thật (Native Windows)

### 2.1. Thử nghiệm khi thiếu biến `ASTRA_LIVE_LLM`:
- **Lệnh thực thi:**
  ```powershell
  backend\.venv\Scripts\python.exe scripts\live_minesweeper_run.py
  ```
- **Kết quả trả về:**
  ```text
  ======================================================================
  THÔNG BÁO: CHƯA KÍCH HOẠT CHẾ ĐỘ LIVE LLM (ASTRA_LIVE_LLM=1)
  ======================================================================
  Theo quy tắc an toàn ngân sách P5, script chỉ được gọi LLM thật khi:
  1. Biến môi trường ASTRA_LIVE_LLM được đặt bằng 1:
     - Windows PowerShell: $env:ASTRA_LIVE_LLM="1"
     - Linux/macOS:        export ASTRA_LIVE_LLM=1
  2. Có ít nhất một API key hợp lệ được cấu hình qua biến môi trường hoặc OS Keyring:
     - OpenAI:   $env:OPENAI_API_KEY="sk-..."
     - Google:   $env:GOOGLE_API_KEY="AIza..."
     - xKiro:    $env:XKIRO_API_KEY="sk-..." (provider=xkiro)
  ======================================================================
  (Exit code: 1, không thực hiện bất kỳ lệnh gọi LLM nào)
  ```

### 2.2. Thử nghiệm khi bật `ASTRA_LIVE_LLM=1` nhưng chưa có API key:
- **Lệnh thực thi:**
  ```powershell
  $env:ASTRA_LIVE_LLM="1"; backend\.venv\Scripts\python.exe scripts\live_minesweeper_run.py
  ```
- **Kết quả trả về:**
  ```text
  ======================================================================
  THÔNG BÁO: THIẾU API KEY CHO LIVE LLM
  ======================================================================
  ASTRA_LIVE_LLM=1 đã được bật, nhưng không tìm thấy API key hợp lệ nào.
  Vui lòng thiết lập một trong các API key sau:
  1. OpenAI:
     $env:OPENAI_API_KEY="sk-..."
     $env:ASTRA_MULTI_PROVIDER="openai"
  2. Google Gemini:
     $env:GOOGLE_API_KEY="AIza..."
     $env:ASTRA_MULTI_PROVIDER="google"
  3. xKiro API:
     $env:XKIRO_API_KEY="sk-..."
     $env:ASTRA_MULTI_PROVIDER="xkiro"
  ======================================================================
  (Exit code: 1, dừng ngay lập tức)
  ```

---

## 3. Bảng Kết Quả 3 Lần Chạy

| Run # | Trạng thái | Số vòng | Blocking Issues Resolved | Reviewer Schema Errors | Tổng Token | Chi phí thực tế | Lý do |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **Run 1** | `NOT_RUN` | 0 | 0/0 | 0 | 0 | $0.00 | Thiếu API key và biến môi trường `ASTRA_LIVE_LLM=1` |
| **Run 2** | `NOT_RUN` | 0 | 0/0 | 0 | 0 | $0.00 | Thiếu API key và biến môi trường `ASTRA_LIVE_LLM=1` |
| **Run 3** | `NOT_RUN` | 0 | 0/0 | 0 | 0 | $0.00 | Thiếu API key và biến môi trường `ASTRA_LIVE_LLM=1` |

---

## 4. Kết Luận Theo Quy Tắc P5.1

Căn cứ quy định tại `AGENT_PROMPTS_P5.md`:
> *"Nếu không có API key, dừng sau bước 1 và báo cáo là chưa chạy được."*  
> *"Nếu P5.1 không chạy được (thiếu key), P5.2 vẫn làm được nhưng bỏ phần ưu tiên theo lỗi live."*

Hệ thống đã dừng lại đúng sau Bước 1. Script sẵn sàng thực thi tự động ngay khi người dùng cấp khóa API và biến môi trường.
