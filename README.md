# Astra Multi

Hệ thống đa tác nhân (Multi-Agent System) phân tích kiến trúc phần mềm độc lập, phản biện dựa trên bằng chứng kỹ thuật và tổng hợp kế hoạch triển khai tự động hóa có thể kiểm chứng.

---

## 1. Badges

![Python Version](https://img.shields.io/badge/python-3.11%2B-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?logo=fastapi)
![LangGraph](https://img.shields.io/badge/LangGraph-0.6%2B-orange)
![React](https://img.shields.io/badge/React-18.x-61DAFB?logo=react)
![TypeScript](https://img.shields.io/badge/TypeScript-5.x-3178C6?logo=typescript)
![Vite](https://img.shields.io/badge/Vite-5.x-646CFF?logo=vite)
![Tests](https://img.shields.io/badge/tests-407%20passed%20%7C%2013%20skipped-success)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

---

## 2. Overview / Introduction

Trong phát triển phần mềm hiện đại, việc sử dụng các mô hình ngôn ngữ lớn (LLM) đơn lẻ để thiết kế kiến trúc hệ thống thường gặp phải những hạn chế nghiêm trọng:
- Hiện tượng ảo giác (hallucination) và giả định sai lệch về mã nguồn hiện hữu.
- Thiếu quá trình tranh luận đa chiều, dẫn đến các giải pháp phi thực tế hoặc tiềm ẩn rủi ro mở rộng.
- Kế hoạch bàn giao mơ hồ, thiếu bằng chứng xác thực và không thể tự động kiểm chứng bằng mã kiểm thử.

**Astra Multi** giải quyết triệt để các vấn đề trên thông qua mô hình **Shared Blackboard có cấu trúc** kết hợp cơ chế phản biện theo từng issue giữa các tác nhân chuyên trách:
- **Planner**: Khởi tạo giải pháp, phân giải mục tiêu thành các bước thực thi cụ thể.
- **Reviewer**: Phản biện độc lập, tìm kiếm lỗ hổng kiến trúc, rủi ro tương thích và yêu cầu bằng chứng.
- **Synthesizer**: Dung hòa các đề xuất, ghi nhận quyết định kiến trúc và cập nhật kế hoạch.
- **Verifier**: Kiểm chứng các giả thuyết và bằng chứng trong môi trường Sandbox cô lập.

Dữ liệu được lưu trữ bền vững (durable persistence) với SQLite WAL, đảm bảo tính toàn vẹn trạng thái thông qua Fenced Leases, kiểm soát nghiêm ngặt qua cổng chất lượng P4 Quality Gates và trực quan hóa qua giao diện Web cục bộ cùng công cụ CLI.

---

## 3. Features

- **Quy trình thảo luận 11 giai đoạn (11-Phase LangGraph Workflow)**:
  `INTAKE` ➔ `SNAPSHOT` ➔ `INVESTIGATE` ➔ `INDEPENDENT_ANALYSIS` ➔ `PROPOSE` ➔ `REVIEW` ➔ `VERIFY` ➔ `REVISE` ➔ `SEMANTIC_REVIEW` ➔ `QUALITY_GATE` ➔ `EXPORT`.
- **Durable Persistence & Fenced Leases**:
  Lưu trữ trạng thái chuẩn tắc (canonical state) trên SQLite với chế độ WAL và `PRAGMA synchronous=FULL`; kiểm soát tranh chấp bằng lease token/epoch fencing, ngăn ngừa xung đột phiên bản và phân tán ghi.
- **Model Gateway đa nhà cung cấp**:
  Tương thích OpenAI, Google Gemini, Anthropic và các endpoint tương thích OpenAI (như xKiro) với cơ chế tự động sửa lỗi đầu ra JSON (output repair), retry thích ứng (exponential backoff) và quản lý ngân sách nghiêm ngặt (token / USD limits).
- **Môi trường thực thi Sandbox cô lập (Isolated Sandboxes)**:
  Thực thi lệnh kiểm chứng độc lập trên cả **Linux Docker** và **Native Windows Subprocess** với kiểm soát tài nguyên, timeout, hủy tác vụ an toàn và tự động che giấu thông tin nhạy cảm (secrets redaction).
- **Cổng chất lượng P4 (Quality Gates & Parity Exporter)**:
  Kiểm tra tĩnh 100% đồ thị phụ thuộc (DAG), mức độ bao phủ yêu cầu (requirements coverage), giải quyết toàn bộ blocking issues, đánh giá ngữ nghĩa (semantic review) và xuất bản đồng nhất định dạng JSON Schema v1 cùng Markdown (chuẩn `PLAN_TEMPLATE.md`).
- **Giao diện Web cục bộ (Local Web UI) & Server-Sent Events (SSE)**:
  Ứng dụng Single-Page Application (React + TypeScript + Vite) hỗ trợ luồng sự kiện real-time, bảng theo dõi tiến trình 11 phase, form tương tác giải đáp thắc mắc của tác nhân (Human-in-the-loop), bảng tra cứu Issues, Decisions, Evidence và Plan Diff.
- **Giao diện dòng lệnh toàn diện (CLI Lifecycle)**:
  Cung cấp công cụ CLI hoàn chỉnh hỗ trợ `create`, `status`, `answer`, `cancel`, `artifacts`, `validate`, `finalize`, và `serve`.

---

## 4. Tech Stack

- **Backend**: Python 3.11+, FastAPI 0.115+, Uvicorn, LangGraph 0.6+, Pydantic v2.
- **Frontend**: React 18, TypeScript 5, Vite, Lucide React.
- **Cơ sở dữ liệu & Lưu trữ**: SQLite (WAL mode, Foreign Keys ON), File Artifact Store (băm nội dung SHA-256).
- **Hạ tầng & Bảo mật**: OS Keyring (`keyring` tích hợp Windows Credential Manager / macOS Keychain / Secret Service), Docker Runner, Windows Subprocess Sandbox.
- **Kiểm thử & Chất lượng mã nguồn**: Pytest, Pytest-Asyncio, Ruff, Mypy.

---

## 5. Installation

### Yêu cầu hệ thống
- **Python**: `>= 3.11`
- **Node.js**: `>= 18.0.0` (Khuyên dùng `>= 20.x` hoặc `24.x`) và npm `>= 9.x`
- **Git**
- *(Tùy chọn)* Docker nếu chạy sandbox trên Linux/WSL2

### Các bước cài đặt

1. **Clone mã nguồn dự án**:
   ```powershell
   git clone https://github.com/suler7080/astra-multi.git
   cd astra-multi
   ```

2. **Cài đặt Backend**:
   ```powershell
   cd backend
   # Tạo môi trường ảo
   python -m venv .venv
   
   # Kích hoạt môi trường ảo (Windows PowerShell)
   .venv\Scripts\Activate.ps1
   # (Trên Linux/macOS: source .venv/bin/activate)

   # Cài đặt các gói phụ thuộc
   pip install -r requirements.lock
   # Hoặc cài đặt ở chế độ phát triển
   pip install -e .[dev,providers]
   cd ..
   ```

3. **Cài đặt và Build Frontend**:
   ```powershell
   cd frontend
   npm install
   npm run build
   cd ..
   ```

---

## 6. Usage

### 6.1. Khởi chạy Ứng dụng Web & API Dashboard (Khuyên dùng)
FastAPI tự động phục vụ hệ thống API endpoints, Server-Sent Events (SSE) và giao diện Web UI Single-Page Application (SPA):
```powershell
cd backend
.\.venv\Scripts\python -m astra_multi.cli serve --host 127.0.0.1 --port 8000
```
Truy cập trình duyệt tại địa chỉ: **`http://127.0.0.1:8000`**

- **Dashboard & Quản lý Phiên (Sessions):** Tạo phiên thiết kế mới, xem danh sách các phiên chạy, trạng thái hoàn thành và tiến độ trực quan.
- **Theo dõi Tiến trình Real-Time (SSE PhaseTracker):** Tự động đồng bộ hóa luồng sự kiện qua 11 giai đoạn (`INTAKE` ➔ `EXPORT`) không cần tải lại trang.
- **Xác thực Admin & Cấu hình LLM Providers:**
  - Nhấp vào biểu tượng **Settings** trên thanh tiêu đề (Header).
  - Lần đầu sử dụng: Thiết lập mật khẩu quản trị viên (Admin Password).
  - Cấu hình khóa API, endpoint và model cho **OpenAI**, **Google Gemini**, **Anthropic**, hoặc **xKiro** (hỗ trợ mô hình mã nguồn mở miễn phí như `xkiro/llama-3.1-70b-instruct`).
- **Chuyển đổi Đa ngôn ngữ (i18n):** Nút chuyển đổi nhanh **Tiếng Việt / English** ngay trên Header.
- **Trình xem Nhật ký Thực thi (Execution Log Viewer):** Theo dõi chi tiết log vận hành, sự kiện vòng lặp, cảnh báo và lỗi hệ thống cho từng phiên chạy.

### 6.2. Phát triển Frontend với Hot-Reload (Dev Mode)
Nếu bạn đang chỉnh sửa hoặc tùy biến mã nguồn giao diện:
- **Terminal 1 (Backend API & SSE Server):**
  ```powershell
  cd backend
  .\.venv\Scripts\python -m astra_multi.cli serve --port 8000
  ```
- **Terminal 2 (Vite Dev Server):**
  ```powershell
  cd frontend
  npm run dev
  ```
  Truy cập giao diện tại: **`http://localhost:5173`** (Vite tự động proxy các yêu cầu `/api` về cổng `8000`).

### 6.3. Thao tác Toàn diện qua Giao diện Dòng lệnh (CLI)
Astra Multi cung cấp bộ lệnh CLI hoàn chỉnh phục vụ quản trị và tự động hóa toàn bộ vòng đời phiên thiết kế:

- **1. Tạo một phiên thiết kế mới:**
  ```powershell
  cd backend
  .\.venv\Scripts\python -m astra_multi.cli create `
    --goal "Thiết kế Payment Gateway chịu lỗi cao" `
    --requirements "Hỗ trợ 10k TPS" "Đảm bảo tính nhất quán dữ liệu giao dịch"
  ```
  *(Lệnh sẽ trả về mã định danh `RUN-xxxxxx` của phiên vừa tạo).*

- **2. Kiểm tra trạng thái và tóm tắt tiến trình:**
  ```powershell
  .\.venv\Scripts\python -m astra_multi.cli status RUN-xxxxxx
  ```

- **3. Xem nhật ký thực thi (Execution Logs):**
  ```powershell
  # Xem toàn bộ nhật ký sự kiện
  .\.venv\Scripts\python -m astra_multi.cli logs RUN-xxxxxx

  # Lọc theo cấp độ cảnh báo hoặc lỗi
  .\.venv\Scripts\python -m astra_multi.cli logs RUN-xxxxxx --level ERROR

  # Xuất nhật ký dưới dạng raw JSON
  .\.venv\Scripts\python -m astra_multi.cli logs RUN-xxxxxx --json
  ```

- **4. Trả lời câu hỏi tương tác từ tác nhân (Human-in-the-Loop):**
  ```powershell
  .\.venv\Scripts\python -m astra_multi.cli answer RUN-xxxxxx Q-001 `
    --answer "Sử dụng kiến trúc Event Sourcing với PostgreSQL"
  ```

- **5. Thẩm định chất lượng cấu trúc (Quality Gate Validation):**
  ```powershell
  .\.venv\Scripts\python -m astra_multi.cli validate RUN-xxxxxx
  ```

- **6. Đánh giá chất lượng và chứng nhận hoàn tất (Finalize):**
  ```powershell
  .\.venv\Scripts\python -m astra_multi.cli finalize RUN-xxxxxx
  ```

- **7. Xuất bản Artifacts kế hoạch (Markdown / JSON):**
  ```powershell
  # Xuất kế hoạch kiến trúc chuẩn Markdown (chuẩn PLAN_TEMPLATE.md)
  .\.venv\Scripts\python -m astra_multi.cli artifacts RUN-xxxxxx --format markdown

  # Xuất toàn bộ cấu trúc trạng thái dưới dạng JSON
  .\.venv\Scripts\python -m astra_multi.cli artifacts RUN-xxxxxx --format json
  ```

- **8. Hủy hoặc xóa phiên chạy:**
  ```powershell
  # Hủy phiên đang chạy
  .\.venv\Scripts\python -m astra_multi.cli cancel RUN-xxxxxx --reason "Thay đổi phạm vi yêu cầu"

  # Xóa phiên vĩnh viễn (kèm dọn dẹp artifacts)
  .\.venv\Scripts\python -m astra_multi.cli delete RUN-xxxxxx --force
  ```

### 6.4. Chạy Thử nghiệm Mô phỏng và Live Run với LLM Thật

- **Chạy Thử nghiệm Live Run có Trần Ngân sách Cứng (Hard Budget Cap):**
  Để bảo đảm an toàn chi phí, việc gọi LLM thực tế bắt buộc phải có cờ `ASTRA_LIVE_LLM=1` cùng API key hợp lệ:
  ```powershell
  # Thiết lập môi trường và khóa API
  $env:ASTRA_LIVE_LLM="1"
  $env:OPENAI_API_KEY="sk-..."  # Hoặc GOOGLE_API_KEY, XKIRO_API_KEY
  $env:ASTRA_MULTI_PROVIDER="openai"

  # Chạy kịch bản Minesweeper (mặc định giới hạn ngân sách cứng 1.00 USD)
  .\backend\.venv\Scripts\python scripts/live_minesweeper_run.py --budget-cap 1.00
  ```

- **Đo lường Token & Kiểm soát Phình to Prompt (Prompt Bloat):**
  Đo đạc số lượng token thực tế của từng tác nhân qua 5 vòng lặp:
  ```powershell
  .\backend\.venv\Scripts\python scripts/measure_prompt_bloat.py
  ```

- **Chạy Bộ Đánh giá Đa tác nhân (Multi-Agent Evaluations):**
  ```powershell
  .\backend\.venv\Scripts\python evaluations/multi_agent_runner.py
  ```

### 6.5. Chạy Toàn bộ Bộ Kiểm thử (Test Suite)
Dự án duy trì tỷ lệ kiểm thử nghiêm ngặt trên môi trường native Windows:
```powershell
cd backend
.\.venv\Scripts\python -m pytest tests -v
```
*(Kết quả hiện tại: 407 passed, 13 skipped, 0 failed).*

---

## 7. Project Structure

```text
astra-multi/
├── backend/                        # Nguồn mã Backend (Python)
│   ├── pyproject.toml              # Cấu hình dự án & dependencies
│   ├── requirements.lock           # Khóa phiên bản gói phụ thuộc
│   ├── src/astra_multi/            # Gói mã nguồn chính
│   │   ├── agents/                 # Prompts, vai trò Planner, Reviewer, Synthesizer
│   │   ├── api/                    # FastAPI endpoints, Pydantic schemas, SSE Worker
│   │   ├── context/                # Quản lý snapshots, ledger bằng chứng, bundles
│   │   ├── domain/                 # Mô hình dữ liệu chuẩn, policies, commands, state
│   │   ├── exports/                # Quality validator, finalization, plan exporter
│   │   ├── gateway/                # Model gateway, định tuyến, rate limits, retry
│   │   ├── orchestration/          # LangGraph graph, nodes, workflow controller, budget
│   │   ├── persistence/            # SQLite repository, migrations, artifact storage
│   │   ├── providers/              # Adapters cho OpenAI, Google, Anthropic, xKiro
│   │   ├── sandbox/                # Docker runner & Windows subprocess sandbox
│   │   └── cli.py                  # Entrypoint giao diện dòng lệnh CLI
│   └── tests/                      # Bộ kiểm thử tích hợp, unit và recovery (347 tests)
│
├── frontend/                       # Giao diện người dùng Web (React + Vite)
│   ├── src/
│   │   ├── components/             # Header, PhaseTracker, Timeline, PlanViewer, etc.
│   │   ├── api.ts                  # Typed HTTP & SSE client
│   │   ├── types.ts                # TypeScript interfaces tương ứng schema backend
│   │   ├── App.tsx                 # Điều phối views và state tổng
│   │   └── index.css               # Hệ thống styling giao diện hiện đại
│   ├── package.json                # Cấu hình frontend
│   └── vite.config.ts              # Cấu hình Vite & API Proxy
│
├── docs/                           # Tài liệu kỹ thuật chi tiết
│   ├── P1_CONTRACTS.md             # Đặc tả hợp đồng dữ liệu & persistence
│   ├── P2_CONTRACTS.md             # Đặc tả snapshot & execution sandbox
│   ├── adr/                        # Các bản ghi quyết định kiến trúc (ADR-001 -> ADR-006)
│   └── spikes/                     # Báo cáo các đợt thử nghiệm kỹ thuật
│
├── plans/                          # Kế hoạch chi tiết từng giai đoạn P0 -> P6
├── PLAN.md                         # Đặc tả toàn diện kiến trúc hệ thống
├── PLAN_TEMPLATE.md                # Mẫu chuẩn đầu ra kế hoạch kiến trúc
├── IMPLEMENTATION_PLAN.md          # Lộ trình kỹ thuật phân bổ cho dev agents
├── IMPLEMENTATION_STATUS.md        # Bảng theo dõi tiến độ thực tế chi tiết
└── README.md                       # Tài liệu hướng dẫn chính của dự án
```

---

## 8. Configuration

Astra Multi hỗ trợ nạp cấu hình qua biến môi trường hoặc lưu trữ bảo mật qua kho khóa hệ điều hành (OS Keyring):

### Các biến môi trường chính

| Biến môi trường | Bắt buộc | Mô tả |
|---|---|---|
| `OPENAI_API_KEY` | Tùy chọn | Khóa API dịch vụ OpenAI |
| `GOOGLE_API_KEY` | Tùy chọn | Khóa API dịch vụ Google Gemini |
| `ANTHROPIC_API_KEY` | Tùy chọn | Khóa API dịch vụ Anthropic |
| `ASTRA_MULTI_PROFILE` | Không | Chỉ định profile cấu hình mặc định |
| `PYTHONIOENCODING` | Khuyên dùng | Đặt `utf-8` trên Windows để hiển thị ký tự chuẩn |

### Quản lý khóa an toàn qua OS Credential Store
Để tránh lộ khóa API trong tệp cấu hình phẳng, Astra Multi hỗ trợ lưu khóa trực tiếp vào OS Keyring (Windows Credential Manager, macOS Keychain, Linux Secret Service):
```powershell
# Xem hướng dẫn chi tiết tại docs/PROVIDER_CONFIGURATION.md
.venv\Scripts\python -m astra_multi.provider_smoke default
```

---

## 9. Contributing

Mọi đóng góp cho dự án đều được hoan nghênh. Vui lòng tuân thủ các quy tắc sau:

1. **Định hướng nhánh**:
   - Mọi Pull Request phải nhắm vào nhánh `main`. Không đẩy mã trực tiếp lên nhánh `main` khi chưa qua kiểm thử.
2. **Quy chuẩn mã nguồn**:
   - Đảm bảo kiểm tra cú pháp và định dạng mã nguồn:
     ```powershell
     cd backend
     .venv\Scripts\python -m ruff check src/ tests/
     ```
3. **Kiểm thử bắt buộc**:
   - Toàn bộ bài kiểm tra phải PASS trước khi gửi PR:
     ```powershell
     cd backend
     .venv\Scripts\python -m pytest tests/ -v
     ```
   - Nếu có chỉnh sửa Frontend, đảm bảo bản build không phát sinh lỗi TypeScript:
     ```powershell
     cd frontend
     npm run build
     ```
4. **Cam kết thay đổi**:
   - Thực hiện thay đổi chính xác, không xóa bỏ các ghi chú hoặc mã không liên quan. Tuân thủ commit message theo định dạng chuẩn Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`).

---

## 10. License

Dự án được phân phối dưới giấy phép [MIT License](LICENSE).
