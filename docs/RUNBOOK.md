# Sổ tay Vận hành Hệ thống Astra Multi (Operations Runbook)

Tài liệu hướng dẫn triển khai, vận hành, bảo trì, sao lưu và xử lý sự cố cho hệ thống Astra Multi trong môi trường thử nghiệm (Pilot) và phát triển cục bộ (Local MVP).

---

## 1. Cài đặt từ môi trường sạch (Clean Setup)

### Yêu cầu tiên quyết
- **Hệ điều hành:** Windows 10/11 / Windows Server 2022 hoặc Linux (Ubuntu 22.04+).
- **Python:** Phiên bản `>= 3.11` (khuyên dùng Python 3.11.7+).
- **Node.js:** Phiên bản `>= 18.0.0` (khuyên dùng `>= 20.x` hoặc `24.x`) và npm `>= 9.x`.
- **Git**
- *(Tùy chọn)* Docker Desktop nếu muốn chạy Sandbox trên Linux Container từ Windows.

### Các bước cài đặt chi tiết

1. **Clone repository:**
   ```powershell
   git clone https://github.com/suler7080/astra-multi.git
   cd astra-multi
   ```

2. **Cài đặt Backend:**
   ```powershell
   cd backend
   # Tạo môi trường ảo
   python -m venv .venv

   # Kích hoạt môi trường ảo (Windows PowerShell)
   .venv\Scripts\Activate.ps1
   # (Trên Linux: source .venv/bin/activate)

   # Cài đặt gói phụ thuộc từ lockfile
   pip install -r requirements.lock
   pip install -e .[dev,providers]
   cd ..
   ```

3. **Cài đặt và Đóng gói Frontend Web UI:**
   ```powershell
   cd frontend
   npm install
   npm run build
   cd ..
   ```

4. **Kiểm tra cài đặt hoàn chỉnh (Smoke Test):**
   ```powershell
   cd backend
   .venv\Scripts\python -m pytest tests/unit/test_cli.py -v
   ```

---

## 2. Cấu hình Nhà cung cấp Mô hình (Provider Configuration) & Kho khóa OS

Astra Multi hỗ trợ hai phương thức nạp khóa API:
1. **Biến môi trường (Environment Variables):**
   - `OPENAI_API_KEY`: Khóa API dịch vụ OpenAI.
   - `GOOGLE_API_KEY`: Khóa API dịch vụ Google Gemini.
   - `ANTHROPIC_API_KEY`: Khóa API dịch vụ Anthropic.
   - `ASTRA_MULTI_PROFILE`: Chỉ định profile cấu hình mặc định (tùy chọn).

2. **Lưu trữ bảo mật qua OS Credential Store (Khuyên dùng):**
   - Tránh lưu trữ khóa bí mật trong các tệp phẳng (`.env` hay `config.json`).
   - Sử dụng thư viện `keyring` tích hợp sẵn với **Windows Credential Manager** (trên Windows) hoặc **Secret Service / Keychain** (trên Linux/macOS).
   - Kiểm tra kết nối và cấu hình an toàn bằng công cụ smoke test:
     ```powershell
     cd backend
     .venv\Scripts\python -m astra_multi.provider_smoke default
     ```

---

## 3. Lựa chọn Môi trường Thực thi Cô lập (Sandbox Isolation)

Astra Multi cung cấp hai cơ chế sandbox kiểm chứng:

### A. Windows Native Subprocess Runner (Mặc định trên Windows)
- Tận dụng quy trình con (`subprocess.Popen`) với giới hạn tài nguyên nghiêm ngặt:
  - Timeout thực thi tối đa (mặc định 15 giây, tối đa 600 giây).
  - Giới hạn kích thước output (mặc định 64KB, cắt ngắn an toàn nếu vượt quá).
  - Tự động dọn dẹp thư mục làm việc tạm thời (`work_root`) sau mỗi tác vụ.
  - Tự động che giấu (redaction) chuỗi khóa bí mật và thông tin nhạy cảm.

### B. Linux Docker Runner
- Sử dụng container Docker cô lập hoàn toàn (`target_os: linux`):
  - Yêu cầu Docker Engine/Desktop đang chạy.
  - Cách ly mạng hoàn toàn (`network: none`).
  - Giới hạn RAM (mặc định 256MB), CPU (1.0 core), PIDs (64).
  - Nếu daemon Docker không khả dụng, hệ thống trả về trạng thái `unavailable` và kết quả kiểm chứng `NOT_RUN` (tuyệt đối không bao giờ báo sai lệch thành `PASS`).

---

## 4. Quy trình Sao lưu & Phục hồi Nhất quán (Backup & Consistent Restore)

Do Astra Multi sử dụng SQLite ở chế độ **WAL (Write-Ahead Logging)** kết hợp cùng kho lưu trữ file artifact định danh theo mã băm SHA-256 (`artifacts/`), việc sao lưu cần tuân thủ quy trình sau để đảm bảo tính nhất quán (Consistent Point-in-time Snapshot):

### Quy trình Sao lưu (Backup)
1. **Sao lưu Cơ sở dữ liệu qua SQLite Online Backup API:**
   Không copy trực tiếp file `.sqlite` khi tiến trình đang ghi! Hãy chạy checkpoint hoặc sử dụng SQLite backup API:
   ```powershell
   # Sử dụng script Python tích hợp
   python -c "import sqlite3; src = sqlite3.connect('state.sqlite'); dst = sqlite3.connect('backup/state.sqlite'); src.backup(dst); dst.close(); src.close()"
   ```
2. **Sao lưu Thư mục Artifacts:**
   Vì file trong thư mục `artifacts/` là bất biến (đặt tên theo hash SHA-256 nội dung), bạn có thể copy an toàn toàn bộ thư mục:
   ```powershell
   Copy-Item -Path "artifacts" -Destination "backup\artifacts" -Recurse
   ```

### Quy trình Phục hồi (Restore)
1. Đảm bảo dịch vụ `astra-multi serve` đã dừng.
2. Sao chép tệp `backup/state.sqlite` và thư mục `backup/artifacts` vào thư mục làm việc mục tiêu.
3. Khởi động lại dịch vụ `astra-multi serve`.
4. Kiểm tra tính toàn vẹn trạng thái bằng lệnh:
   ```powershell
   python -m astra_multi.cli status RUN-xxxxxx
   ```

---

## 5. Quản lý Cơ sở dữ liệu và Schema Migrations

- Quá trình khởi tạo cơ sở dữ liệu và di chuyển lược đồ (schema migration) được tự động hóa hoàn toàn bởi `SQLiteStore` thông qua module `astra_multi.persistence.migrations`.
- Mọi kết nối SQLite đều tự động bật:
  - `PRAGMA foreign_keys = ON;`
  - `PRAGMA journal_mode = WAL;`
  - `PRAGMA synchronous = FULL;`
  - `PRAGMA busy_timeout = 5000;` (5.0s chống nghẽn ghi).
- Quản lý tranh chấp ghi được bảo vệ bằng cơ chế **Fenced Lease (Epoch-based)**, ngăn chặn hoàn toàn hai tiến trình cùng sửa đổi dữ liệu một lúc.

---

## 6. Bảo vệ Quyền riêng tư & Che giấu Khóa (Redaction Policy)

- Toàn bộ lệnh shell và đối số truyền vào Sandbox đều đi qua bộ lọc `redact_secrets()`.
- Các giá trị khóa API (`OPENAI_API_KEY`, chuỗi hash nhạy cảm) được thay thế tự động bằng `[REDACTED]` trước khi lưu trữ vào bảng `tool_calls` hay `validations`.
- Log phát ra từ SSE stream và API response không chứa khóa bí mật.

---

## 7. Xử lý Sự cố Thường gặp (Troubleshooting)

### Sự cố 1: `sqlite3.OperationalError: database is locked`
- **Nguyên nhân:** Nhiều tiến trình cố gắng ghi đồng thời khi tiến trình trước chưa giải phóng giao dịch.
- **Khắc phục:** 
  1. Kiểm tra xem có worker nào bị treo không: `tasklist | findstr python`.
  2. Thời gian chờ mặc định là 5000ms. Cơ chế `SQLiteStore` có retry tự động.
  3. Đảm bảo database file nằm trên ổ đĩa cục bộ (Local SSD/HDD), không đặt database SQLite trên thư mục mạng SMB/NFS chia sẻ.

### Sự cố 2: `Port 8000 already in use`
- **Nguyên nhân:** Có tiến trình uvicorn hoặc web server khác đang chiếm cổng 8000.
- **Khắc phục:**
  - Chạy `netstat -ano | findstr :8000` để lấy PID và dừng tiến trình.
  - Hoặc chỉ định cổng khác: `python -m astra_multi.cli serve --port 8080`.

### Sự cố 3: Sandbox trả về `unavailable` / `NOT_RUN`
- **Nguyên nhân:** Chạy kịch bản Linux Docker trên Windows khi Docker Desktop chưa bật hoặc chưa cài đặt WSL2.
- **Khắc phục:**
  - Hệ thống được thiết kế để tự động chuyển sang `WindowsRunner` khi chạy native trên Windows.
  - Nếu cần kiểm thử Linux, khởi động Docker Desktop trước khi chạy tác vụ.

### Sự cố 4: `409 Conflict: Expected revision mismatch`
- **Nguyên nhân:** Thao tác trả lời câu hỏi hoặc cập nhật plan dựa trên một revision cũ đã bị tác nhân khác thay thế.
- **Khắc phục:** Gọi lại `GET /api/runs/{id}` để lấy `revision` hiện tại trước khi gửi request.

---

## 8. Nền tảng Hỗ trợ & Giới hạn Kỹ thuật (Supported Platforms & Limitations)

### Nền tảng được hỗ trợ chính thức
- **Windows:** Windows 10, Windows 11, Windows Server 2022 (Native 64-bit).
- **Linux:** Ubuntu 22.04 LTS, Debian 12 (x86_64).

### Giới hạn kỹ thuật đã biết (Known Limitations - Local MVP)
1. **Phạm vi triển khai:** Hệ thống được thiết kế tối ưu cho mô hình **Local-first MVP** (mỗi máy trạm chạy một máy chủ cục bộ phục vụ một kỹ sư thiết kế kiến trúc). Chưa hỗ trợ phân cụm multi-tenant phân tán qua nhiều máy chủ mạng.
2. **Giới hạn SQLite Concurrency:** SQLite tối ưu cho mô hình đơn ghi - đa đọc (Single-writer / Multiple-readers). Khi tải ghi vượt quá 100 tác vụ/giây, nên cân nhắc nâng cấp adapter sang PostgreSQL trong các phiên bản sau.
3. **Giới hạn kích thước Artifacts:** Mặc định mỗi file output từ Sandbox hoặc snapshot giới hạn ở 64KB - 1MB để đảm bảo hiệu năng bộ nhớ.
