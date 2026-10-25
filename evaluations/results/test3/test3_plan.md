# Thiết kế cơ chế phân quyền cho 3 vai trò (khách, freelancer, nhà tuyển dụng) và bảo vệ trang client-side cho website chợ freelancer. — Kế hoạch triển khai

## 1. Thông tin bản kế hoạch

- Run ID: `RUN-ARCH-TEST3-1791906100`
- Plan revision: `1`
- TaskSpec revision: `1`
- Snapshot ID / manifest hash: `none (greenfield)`
- Trạng thái: **PARTIAL**
- Lý do trạng thái: MVP candidate generated (awaiting P4 quality certification)
- Ngày tạo: `2026-10-13T15:41:40.554613+00:00`

## 2. Mục tiêu và phạm vi

### Mục tiêu

Thiết kế cơ chế phân quyền cho 3 vai trò (khách, freelancer, nhà tuyển dụng) và bảo vệ trang client-side cho website chợ freelancer.

### Yêu cầu và tiêu chí chấp nhận

| Requirement ID | Yêu cầu | Tiêu chí chấp nhận |
|---|---|---|
| `REQ-001` | Cơ chế phân quyền cho 3 vai trò: khách, freelancer, nhà tuyển dụng | Ma trận phân quyền đầy đủ: Vai trò × Trang × Hành động. |
| `REQ-002` | Cơ chế bảo vệ trang và điều hướng trước khi render (Early Guard) | Guard chạy trước khi render DOM nội dung trang để tránh nháy nội dung cấm (flicker). Không dùng thư viện router ngoài. |
| `REQ-003` | Minh bạch về giới hạn và rủi ro bảo mật client-side | Nêu rõ kiểm soát client-side chỉ là trải nghiệm giao diện người dùng, không phải bảo mật thực sự vì người dùng có thể can thiệp devtools/localStorage. Không gợi ý backend nằm ngoài ràng buộc. |
| `REQ-004` | Ma trận vai trò × trang × hành động | Kế hoạch kiến trúc phải có mục thiết kế cụ thể đáp ứng: Ma trận vai trò × trang × hành động |
| `REQ-005` | Cơ chế chặn truy cập trang (guard) chạy trước khi render | Kế hoạch kiến trúc phải có mục thiết kế cụ thể đáp ứng: Cơ chế chặn truy cập trang (guard) chạy trước khi render |
| `REQ-006` | Cách ẩn/hiện thành phần UI theo vai trò | Kế hoạch kiến trúc phải có mục thiết kế cụ thể đáp ứng: Cách ẩn/hiện thành phần UI theo vai trò |
| `REQ-007` | Phần 'Giới hạn và rủi ro' nói thẳng rằng kiểm soát phía client chỉ là trải nghiệm, không phải bảo mật thật | Kế hoạch kiến trúc phải có mục thiết kế cụ thể đáp ứng: Phần 'Giới hạn và rủi ro' nói thẳng rằng kiểm soát phía client chỉ là trải nghiệm, không phải bảo mật thật |

## 3. Quyết định kiến trúc và trade-off

| Decision ID | Vấn đề | Lựa chọn | Alternatives | Lý do |
|---|---|---|---|---|
| `DEC-1` | Làm thế nào để giảm thiểu rủi ro giả mạo vai trò từ biến toàn cục mà không có backend? | Áp dụng cơ chế checksum đơn giản trên đối tượng phiên làm việc và coi biến toàn cục là 'untrusted', luôn validate lại từ nguồn MockAPI trước mỗi lần kiểm tra. | Tin tưởng hoàn toàn vào biến toàn cục sau khi khởi tạo lần đầu., Mã hóa toàn bộ đối tượng session bằng một key cứng trong code. | Vì ràng buộc không có backend nên không thể có chữ ký số thực sự. Tuy nhiên, việc thêm checksum giúp phát hiện các can thiệp thô sơ qua Console và buộc quy trình phải đọc lại từ nguồn gốc (MockAPI) thay vì tin tưởng biến nhớ tạm, giải quyết ISSUE-023db3b6. |
| `DEC-2` | Xử lý như thế nào khi người dùng nhấn nút Back sau khi bị Early Guard chặn? | Sử dụng history.replaceState để thay thế trạng thái hiện tại bằng trạng thái của trang an toàn (ví dụ: trang chủ hoặc 403) thay vì đẩy thêm lịch sử. | Vô hiệu hóa hoàn toàn nút Back của trình duyệt., Cho phép quay lại nhưng hiển thị nội dung rỗng. | Cách tiếp cận này loại bỏ entry 'bị chặn' khỏi ngăn xếp lịch sử trình duyệt, ngăn chặn hoàn toàn khả năng người dùng quay lại trang đó và kích hoạt vòng lặp chuyển hướng vô tận, giải quyết ISSUE-5ffe1c88. |

## 4. Thiết kế

### ART-1 — Session State & Integrity Check (state_machine)

- **Loại:** `state_machine`
- **Requirements:** `REQ-001`, `REQ-003`

States: [Uninitialized, Loading, Valid, Invalid/Tampered]. Transitions: Start -> Loading (fetch MockAPI); Loading -> Valid (if checksum matches source); Loading -> Invalid (if mismatch detected); Any -> Uninitialized (on logout). Action on Invalid: Force reload from MockAPI or redirect to safe zone.

### ART-2 — Navigation Guard & History Handling (sequence_flow)

- **Loại:** `sequence_flow`
- **Requirements:** `REQ-002`, `REQ-005`

1. User triggers navigation (click or back button). 2. Router intercepts event. 3. Early Guard calls checkAccess(route, currentRole). 4. IF denied: Call history.replaceState(safeUrl) to overwrite current bad entry, then render 403 or redirect. 5. IF allowed: Call history.pushState(targetUrl) and renderPage().

### ART-3 — PermissionMatrix Structure (message_schema)

- **Loại:** `message_schema`
- **Requirements:** `REQ-004`

Object format: { 'guest': { '/home': ['view'], '/profile': [] }, 'freelancer': { '/home': ['view'], '/jobs': ['view', 'apply'] }, 'employer': { '/home': ['view'], '/post-job': ['create', 'edit'] } }. Keys are roles, nested keys are routes, values are arrays of allowed action strings.

### ART-4 — Client-Side Security Limitations (failure_modes)

- **Loại:** `failure_modes`
- **Requirements:** `REQ-003`, `REQ-007`

Failure Mode: User modifies global role variable via Console. Impact: Unauthorized access to UI views. Mitigation: Documentation explicitly states this is UX protection only; Checksum logic adds a layer of difficulty but is not cryptographic security. System assumes MockAPI is the single source of truth for the current session.

## 5. Các bước thực hiện

### STEP-1 — Thiết kế và định nghĩa Ma trận Phân quyền (PermissionMatrix) và cấu trúc dữ liệu phiên làm việc an toàn.

- **Mục tiêu:** Thiết kế và định nghĩa Ma trận Phân quyền (PermissionMatrix) và cấu trúc dữ liệu phiên làm việc an toàn.
- **Requirements:** `REQ-001`, `REQ-004`
- **Phụ thuộc:** không có
- **Đầu ra bàn giao:** Bảng ánh xạ Role-Page-Action, Mô tả đối tượng SessionManager
- **Cách xác minh:** Kiểm tra xem ma trận có phủ kín 3 vai trò và các trang đích hay không; xác nhận cấu trúc session bao gồm trường dữ liệu và trường checksum/signature giả lập.
- **Tiêu chí hoàn thành:** Ma trận phân quyền được định nghĩa rõ ràng cho Khách, Freelancer, Nhà tuyển dụng., Cơ chế tạo checksum đơn giản (ví dụ: hash chuỗi JSON vai trò + salt cố định) được mô tả để phát hiện thay đổi thô sơ.

### STEP-2 — Thiết kế cơ chế Early Guard xử lý điều hướng và vòng lặp lịch sử (history loop).

- **Mục tiêu:** Thiết kế cơ chế Early Guard xử lý điều hướng và vòng lặp lịch sử (history loop).
- **Requirements:** `REQ-002`, `REQ-005`
- **Phụ thuộc:** không có
- **Đầu ra bàn giao:** Spec lớp Router tùy chỉnh, Kịch bản xử lý lỗi điều hướng
- **Cách xác minh:** Xác nhận logic sử dụng history.replaceState khi phát hiện truy cập trái phép để ngăn chặn nút Back gây vòng lặp.
- **Tiêu chí hoàn thành:** Guard chạy đồng bộ trước khi render DOM., Logic xử lý popstate明确规定: nếu truy cập bị chặn, dùng replaceState đẩy người dùng về trang an toàn thay vì pushState.

### STEP-3 — Thiết kế cơ chế hiển thị UI theo vai trò và tài liệu giới hạn bảo mật.

- **Mục tiêu:** Thiết kế cơ chế hiển thị UI theo vai trò và tài liệu giới hạn bảo mật.
- **Requirements:** `REQ-003`, `REQ-006`, `REQ-007`
- **Phụ thuộc:** không có
- **Đầu ra bàn giao:** Mô tả utility UI, Tuyên bố miễn trừ trách nhiệm bảo mật (Security Disclaimer)
- **Cách xác minh:** Đối chiếu lại các cảnh báo từ ISSUE-023db3b6 và ISSUE-5ffe1c88 đã được giải quyết trong thiết kế chi tiết.
- **Tiêu chí hoàn thành:** Hàm ẩn/hiện UI dựa trên vai trò hiện tại được định nghĩa., Tài liệu nêu rõ biến toàn cục là 'untrusted' và cơ chế client-side chỉ mang tính UX., Giải pháp thay thế history state để tránh redirect loop được ghi nhận.

## 6. Issues, rủi ro và trạng thái

| ID | Nội dung | Mức độ | Trạng thái | Hướng giải quyết |
|---|---|---|---|---|
| `ISSUE-023db3b6` | Proposal lưu trữ vai trò trong biến toàn cục và đọc từ MockAPI mỗi lần tải mà không đề cập cơ chế chống giả mạo (tampering) ngay tại lớp Session Manager. | warning | resolved | Bổ sung cơ chế checksum hoặc signature đơn giản (dù là client-side) cho đối tượng phiên làm việc để ít nhất phát hiện được sự can thiệp thô sơ trước khi chạy guard, hoặc ghi rõ trong tài liệu rằng biến toàn cục là 'untrusted' và phải luôn được validate lại từ nguồn gốcMockAPI một cách nghiêm ngặt trước mỗi lần kiểm tra. |
| `ISSUE-5ffe1c88` | Cơ chế Early Guard chuyển hướng hoặc hiển thị 403 ngay lập tức nhưng chưa định nghĩa hành vi cụ thể khi người dùng nhấn nút 'Back' trên trình duyệt sau khi bị chặn. | info | open | Làm rõ logic xử lý sự kiện `popstate`: nếu phát hiện điều hướng ngược lại vào vùng cấm, hệ thống cần thay thế trạng thái lịch sử (history.replaceState) thay vì đẩy thêm (pushState) để tránh loop. |

## 7. Evidence index

| Evidence ID | Nguồn / locator | Hash | Trạng thái kiểm chứng |
|---|---|---|---|
