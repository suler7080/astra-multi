# Thiết kế cơ chế thống nhất xử lý loading, lỗi mạng, dữ liệu rỗng và hết hạn phiên cho MockAPI trong ứng dụng chợ freelancer. — Kế hoạch triển khai

## 1. Thông tin bản kế hoạch

- Run ID: `RUN-ARCH-TEST2-1791905954`
- Plan revision: `1`
- TaskSpec revision: `1`
- Snapshot ID / manifest hash: `none (greenfield)`
- Trạng thái: **PARTIAL**
- Lý do trạng thái: Max review/revise rounds reached: Còn 1 issue mức warning chưa giải quyết (ISSUE-7ce88cd2); [RULE-ISSUE-002] Issue [ISSUE-7ce88cd2] (severity: warning, status: open) remains open: Cơ chế 'Loading toàn cục' được đề xuất có thể gây xung đột UX khi nhiều request chạy đồng thời (ví dụ: load dữ liệu cho 2 component khác nhau cùng lúc), khiến trạng thái loading bị tắt sớm hoặc kéo dài không đúng.
- Ngày tạo: `2026-10-13T15:39:14.417852+00:00`

## 2. Mục tiêu và phạm vi

### Mục tiêu

Thiết kế cơ chế thống nhất xử lý loading, lỗi mạng, dữ liệu rỗng và hết hạn phiên cho MockAPI trong ứng dụng chợ freelancer.

### Yêu cầu và tiêu chí chấp nhận

| Requirement ID | Yêu cầu | Tiêu chí chấp nhận |
|---|---|---|
| `REQ-001` | Cơ chế thống nhất xử lý loading, lỗi mạng, dữ liệu rỗng và hết hạn phiên cho toàn bộ ứng dụng | Có một điểm vào duy nhất (single entry point / API client wrapper) cho mọi request để quản lý vòng đời và trạng thái. |
| `REQ-002` | Xử lý giới hạn tốc độ và lỗi MockAPI (429/500) | Phân biệt lỗi có thể thử lại (retryable) và lỗi không thể thử lại (non-retryable), áp dụng chiến lược retry có kiểm soát (số lần, khoảng chờ). |
| `REQ-003` | Giao diện phản hồi trạng thái bằng Bootstrap 5 | Thông báo lỗi hiển thị bằng Bootstrap 5 (toast/alert), có xử lý trạng thái rỗng (empty state) và không chặn giao diện vô thời hạn. |
| `REQ-004` | Sơ đồ luồng một request: gửi → loading → thành công/lỗi → render | Kế hoạch kiến trúc phải có mục thiết kế cụ thể đáp ứng: Sơ đồ luồng một request: gửi → loading → thành công/lỗi → render |
| `REQ-005` | Danh sách mã lỗi và cách phản hồi tương ứng trên UI | Kế hoạch kiến trúc phải có mục thiết kế cụ thể đáp ứng: Danh sách mã lỗi và cách phản hồi tương ứng trên UI |
| `REQ-006` | Chiến lược retry (số lần, thời gian chờ) và khi nào không retry | Kế hoạch kiến trúc phải có mục thiết kế cụ thể đáp ứng: Chiến lược retry (số lần, thời gian chờ) và khi nào không retry |
| `REQ-007` | Mẫu mã giả cho hàm bọc request dùng chung | Kế hoạch kiến trúc phải có mục thiết kế cụ thể đáp ứng: Mẫu mã giả cho hàm bọc request dùng chung |

## 3. Quyết định kiến trúc và trade-off

| Decision ID | Vấn đề | Lựa chọn | Alternatives | Lý do |
|---|---|---|---|---|
| `DEC-1` | Làm thế nào để xử lý xung đột UI khi nhiều request đồng thời cùng kích hoạt loading? | Sử dụng bộ đếm tham chiếu (Reference Counter) toàn cục trong ApiClient. | Sử dụng loading cục bộ cho từng component (khó đồng bộ và dễ quên), Dùng hàng đợi request (làm chậm trải nghiệm người dùng không cần thiết) | Giải pháp này đảm bảo trạng thái loading chỉ biến mất khi tất cả các request đang chạy hoàn tất, tránh hiện tượng flicker hoặc ẩn loading sớm khi vẫn còn dữ liệu chưa về. Đây là cách tiếp cận chuẩn cho các ứng dụng đơn trang (SPA) không dùng framework state management phức tạp. |
| `DEC-2` | Chiến lược xử lý cho mã lỗi 401/403 (hết hạn phiên) nên như thế nào? | Phân loại là non-retryable, không áp dụng backoff, trả về trạng thái đặc biệt để UI điều hướng đăng nhập. | Coi 401/403 như lỗi 500 và retry (sai logic nghiệp vụ), Tự động chuyển hướng sang trang login ngay trong lớp ApiClient (vi phạm nguyên tắc tách biệt logic UI) | Việc retry khi token hết hạn là vô nghĩa và lãng phí tài nguyên nếu không có cơ chế làm mới token tự động (không nằm trong phạm vi yêu cầu). Hành động đúng nhất là thông báo ngay cho người dùng để họ đăng nhập lại, tránh lặp lại request thất bại. |

## 4. Thiết kế

### ART-1 — Luồng xử lý Request với Loading Counter và Retry (sequence_flow)

- **Loại:** `sequence_flow`
- **Requirements:** `REQ-001`, `REQ-002`, `REQ-004`

1. UI gọi ApiClient.request() -> 2. Increment Loading Counter (nếu =1 thì show loading) -> 3. Gửi AJAX -> 4. Nếu lỗi 429/500 và retry < 3: Wait (Backoff) -> Retry; Nếu lỗi 401/403: Dừng ngay, trả về {status: 'unauthorized'}; Nếu lỗi khác: Trả về {status: 'error'} -> 5. Decrement Loading Counter (nếu =0 thì hide loading) -> 6. UI nhận kết quả và render Toast/Redirect.

### ART-2 — Bảng ánh xạ mã lỗi và hành động (failure_modes)

- **Loại:** `failure_modes`
- **Requirements:** `REQ-002`, `REQ-005`, `REQ-006`

429: Retry (Exponential Backoff), Hiển thị Toast 'Máy chủ bận'.
500: Retry (Exponential Backoff), Hiển thị Toast 'Lỗi server' sau khi retry hết.
401/403: NO Retry, Trả về trạng thái 'unauthorized', UI redirect Login.
404: NO Retry, Hiển thị Toast 'Không tìm thấy'.
Network Error: NO Retry, Hiển thị Toast 'Mất kết nối'.

### ART-3 — Trạng thái vòng đời Loading (state_machine)

- **Loại:** `state_machine`
- **Requirements:** `REQ-001`, `REQ-004`

States: [IDLE, ACTIVE]. Transitions: IDLE -> ACTIVE (khi counter 0->1); ACTIVE -> ACTIVE (khi counter >0 và có request mới/kết thúc); ACTIVE -> IDLE (khi counter 1->0). Action On Enter ACTIVE: Show Bootstrap Spinner. Action On Enter IDLE: Hide Spinner.

## 5. Các bước thực hiện

### STEP-1 — Triển khai lớp ApiClient Singleton với cơ chế quản lý trạng thái loading dựa trên bộ đếm tham chiếu (reference counter) để xử lý đồng thời nhiều request.

- **Mục tiêu:** Triển khai lớp ApiClient Singleton với cơ chế quản lý trạng thái loading dựa trên bộ đếm tham chiếu (reference counter) để xử lý đồng thời nhiều request.
- **Requirements:** `REQ-001`, `REQ-004`
- **Phụ thuộc:** không có
- **Đầu ra bàn giao:** Mã nguồn ApiClient với biến toàn cục `_loadingCounter`, Hàm helper `incrementLoading()` và `decrementLoading()`
- **Cách xác minh:** Kiểm tra unit test mô phỏng 3 request khởi động cùng lúc đảm bảo loading chỉ tắt khi cả 3 request đều hoàn tất (counter về 0).
- **Tiêu chí hoàn thành:** Bộ đếm loading tăng khi request bắt đầu, Bộ đếm loading giảm khi request kết thúc (thành công hoặc thất bại), UI loading chỉ ẩn khi bộ đếm bằng 0

### STEP-2 — Cập nhật logic phân loại lỗi HTTP để xử lý đặc biệt mã 401/403 (hết hạn phiên) và bổ sung vào bảng ánh xạ lỗi.

- **Mục tiêu:** Cập nhật logic phân loại lỗi HTTP để xử lý đặc biệt mã 401/403 (hết hạn phiên) và bổ sung vào bảng ánh xạ lỗi.
- **Requirements:** `REQ-002`, `REQ-005`, `REQ-006`
- **Phụ thuộc:** không có
- **Đầu ra bàn giao:** Logic switch-case xử lý status 401/403 riêng biệt, Bảng thông báo lỗi cập nhật cho 401/403, Sự kiện custom 'session:expired' được kích hoạt
- **Cách xác minh:** Kiểm tra tích hợp gửi request giả lập trả về 401/403, xác nhận không có retry xảy ra và callback onError nhận trạng thái 'unauthorized'.
- **Tiêu chí hoàn thành:** Mã 401/403 được đánh dấu là non-retryable, Không áp dụng exponential backoff cho 401/403, Trả về đối tượng kết quả có cờ `isUnauthorized: true`

### STEP-3 — Hoàn thiện hàm wrapper `request()` tích hợp đầy đủ luồng: Loading -&gt; Retry (cho 429/500) -&gt; Xử lý lỗi (401/403/4xx/Network) -&gt; Trả Promise.

- **Mục tiêu:** Hoàn thiện hàm wrapper `request()` tích hợp đầy đủ luồng: Loading -&gt; Retry (cho 429/500) -&gt; Xử lý lỗi (401/403/4xx/Network) -&gt; Trả Promise.
- **Requirements:** `REQ-001`, `REQ-002`, `REQ-003`, `REQ-007`
- **Phụ thuộc:** không có
- **Đầu ra bàn giao:** Hàm `ApiClient.request(url, options)` hoàn chỉnh, Cơ chế Exponential Backoff (1s, 2s, 4s), Xử lý timeout cứng cho toàn bộ quá trình
- **Cách xác minh:** Chạy suite test bao gồm: request thành công, lỗi mạng, lỗi 429 (retry 3 lần), lỗi 500 (retry 3 lần), lỗi 401 (không retry), lỗi 404 (không retry).
- **Tiêu chí hoàn thành:** Hàm trả về Promise luôn resolve (với metadata trạng thái) thay vì reject thô, Đảm bảo tách biệt hoàn toàn logic network và UI rendering

### STEP-4 — Xây dựng tài liệu thiết kế chi tiết bao gồm sơ đồ luồng, bảng mã lỗi và mẫu code giả.

- **Mục tiêu:** Xây dựng tài liệu thiết kế chi tiết bao gồm sơ đồ luồng, bảng mã lỗi và mẫu code giả.
- **Requirements:** `REQ-004`, `REQ-005`, `REQ-007`
- **Phụ thuộc:** không có
- **Đầu ra bàn giao:** Sơ đồ sequence diagram, Bảng mapping lỗi chi tiết, Mẫu code usage cho UI component
- **Cách xác minh:** Review tài liệu đảm bảo mô tả đúng cơ chế counter loading và quy trình điều hướng khi gặp 401.
- **Tiêu chí hoàn thành:** Tài liệu phê duyệt bởi nhóm phát triển, Cover đầy đủ các case edge đã xác định

## 6. Issues, rủi ro và trạng thái

| ID | Nội dung | Mức độ | Trạng thái | Hướng giải quyết |
|---|---|---|---|---|
| `ISSUE-e1d89b5b` | Proposal thiếu cơ chế xử lý cụ thể cho yêu cầu 'hết hạn phiên' (session expiration) thường tương ứng với mã lỗi 401 hoặc 403, dù đây là một phần của mục tiêu nhiệm vụ. | blocking | resolved | Bổ sung vào bảng ánh xạ mã lỗi (REQ-005) và logic wrapper (REQ-002) cách xử lý đặc biệt cho lỗi 401/403: không retry, trả về trạng thái 'unauthorized' và kích hoạt sự kiện để UI điều hướng người dùng đến trang đăng nhập. |
| `ISSUE-7ce88cd2` | Cơ chế 'Loading toàn cục' được đề xuất có thể gây xung đột UX khi nhiều request chạy đồng thời (ví dụ: load dữ liệu cho 2 component khác nhau cùng lúc), khiến trạng thái loading bị tắt sớm hoặc kéo dài không đúng. | warning | open | Làm rõ cơ chế quản lý vòng đời loading: sử dụng bộ đếm tham chiếu (reference counter) tăng/giảm khi bắt đầu/kết thúc request. Chỉ ẩn loading khi bộ đếm về 0. |

## 7. Evidence index

| Evidence ID | Nguồn / locator | Hash | Trạng thái kiểm chứng |
|---|---|---|---|
