# Thiết kế kiến trúc front-end cho website chợ freelancer (đăng việc, tìm việc, xem hồ sơ, nhắn tin cơ bản) đáp ứng hoàn toàn ràng buộc thuần front-end và tĩnh. — Kế hoạch triển khai

## 1. Thông tin bản kế hoạch

- Run ID: `RUN-ARCH-TEST1-1791905644`
- Plan revision: `1`
- TaskSpec revision: `1`
- Snapshot ID / manifest hash: `none (greenfield)`
- Trạng thái: **PARTIAL**
- Lý do trạng thái: MVP candidate generated (awaiting P4 quality certification)
- Ngày tạo: `2026-10-13T15:34:04.762841+00:00`

## 2. Mục tiêu và phạm vi

### Mục tiêu

Thiết kế kiến trúc front-end cho website chợ freelancer (đăng việc, tìm việc, xem hồ sơ, nhắn tin cơ bản) đáp ứng hoàn toàn ràng buộc thuần front-end và tĩnh.

### Yêu cầu và tiêu chí chấp nhận

| Requirement ID | Yêu cầu | Tiêu chí chấp nhận |
|---|---|---|
| `REQ-001` | Hệ thống front-end thuần cho chợ freelancer chạy hoàn toàn trên static hosting | Chỉ sử dụng HTML, CSS, Vanilla JS, jQuery, Bootstrap 5. Không dùng bất kỳ framework SPA nào (React, Vue, Angular) hay backend riêng. Tương thích static hosting. |
| `REQ-002` | Giao tiếp dữ liệu qua MockAPI | Toàn bộ dữ liệu được lấy từ MockAPI qua lớp API tập trung, không phân tán lệnh AJAX/fetch trong các trang. |
| `REQ-003` | Cơ chế làm việc song song cho 4 lập trình viên | Cấu trúc mã nguồn và phân công module rõ ràng, không để hai lập trình viên sửa cùng một file nhằm tránh xung đột mã. |
| `REQ-004` | Sơ đồ cấu trúc thư mục (pages, components/partials, js/api, js/utils, css) | Kế hoạch kiến trúc phải có mục thiết kế cụ thể đáp ứng: Sơ đồ cấu trúc thư mục (pages, components/partials, js/api, js/utils, css) |
| `REQ-005` | Quy ước tách lớp: gọi API / xử lý dữ liệu / render DOM | Kế hoạch kiến trúc phải có mục thiết kế cụ thể đáp ứng: Quy ước tách lớp: gọi API / xử lý dữ liệu / render DOM |
| `REQ-006` | Cách dùng lại header/footer giữa các trang không cần framework | Kế hoạch kiến trúc phải có mục thiết kế cụ thể đáp ứng: Cách dùng lại header/footer giữa các trang không cần framework |
| `REQ-007` | Cơ chế quản lý trạng thái đăng nhập (localStorage/sessionStorage) | Kế hoạch kiến trúc phải có mục thiết kế cụ thể đáp ứng: Cơ chế quản lý trạng thái đăng nhập (localStorage/sessionStorage) |
| `REQ-008` | Bảng phân công module cho 4 thành viên | Kế hoạch kiến trúc phải có mục thiết kế cụ thể đáp ứng: Bảng phân công module cho 4 thành viên |

## 3. Quyết định kiến trúc và trade-off

| Decision ID | Vấn đề | Lựa chọn | Alternatives | Lý do |
|---|---|---|---|---|
| `DEC-1` | Làm thế nào để giảm thiểu rủi ro bảo mật XSS khi bắt buộc sử dụng localStorage trong kiến trúc thuần tĩnh? | Áp dụng chiến lược phòng thủ chiều sâu: (1) Thiết lập Content Security Policy (CSP) chặt chẽ qua thẻ meta để vô hiệu hóa inline-script và hạn chế nguồn tài nguyên; (2) Bắt buộc sử dụng hàm sanitizeHTML() (dựa trên regex hoặc library nhẹ) cho mọi dữ liệu động từ API trước khi render vào DOM; (3) Thay đổi cơ chế lưu trữ: chỉ lưu một 'session_id' ngẫu nhiên hoặc flag boolean 'is_logged_in' thay vì lưu toàn bộ token nhạy cảm, chấp nhận việc người dùng phải đăng nhập lại sau khi đóng trình duyệt (session ngắn hạn). | Lưu token đầy đủ trong localStorage và hy vọng dữ liệu API sạch (Rủi ro quá cao, không chấp nhận được), Mã hóa token trước khi lưu vào localStorage (Vẫn bị lộ nếu key mã hóa nằm trong JS client-side), Chuyển sang dùng Hash-based URL để giả lập SPA (Tăng độ phức tạp không cần thiết, không giải quyết gốc rễ vấn đề XSS) | Trong môi trường không có backend để thiết lập HttpOnly cookies, localStorage là lựa chọn duy nhất nhưng rất rủi ro. CSP giúp ngăn chặn việc thực thi mã độc injected. Sanitization dữ liệu ngăn chặn việc mã độc được chèn vào nội dung trang. Việc không lưu token dài hạn giảm thiểu thiệt hại nếu kẻ tấn công vượt qua được hai lớp bảo vệ đầu tiên, biến rủi ro từ 'chiếm quyền vĩnh viễn' thành 'phiên làm việc tạm thời'. |
| `DEC-2` | Làm sao để khắc phục hiện tượng nháy trang (layout shift) và lỗi giao diện khi tải header/footer động bằng jQuery? | Sử dụng kỹ thuật 'Hidden Content until Loaded': Ẩn toàn bộ vùng nội dung chính (main container) bằng CSS (display: none hoặc opacity: 0) ngay từ đầu. Chỉ hiển thị nội dung này sau khi sự kiện load của cả header và footer hoàn thành thành công. Đồng thời, thêm khối xử lý lỗi (.fail()) vào lệnh jQuery.load() để hiển thị một giao diện fallback đơn giản (ví dụ: text tĩnh 'Menu' hoặc thông báo lỗi) nếu file component không tải được. | Nhúng cứng header/footer vào từng file HTML (Vi phạm nguyên tắc DRY, khó bảo trì), Hiển thị skeleton loader phức tạp (Tốn công sức implement cho một dự án tĩnh đơn giản), Chấp nhận hiện tượng nháy như một hạn chế (Không đạt chuẩn UX chuyên nghiệp) | Cách tiếp cận này đảm bảo người dùng không bao giờ thấy trạng thái trung gian 'trống rỗng' hoặc 'thiếu đầu đuôi'. Cơ chế fallback đảm bảo ứng dụng vẫn sử dụng được (degrade gracefully) ngay cả khi file component bị xóa hoặc lỗi mạng, đáp ứng yêu cầu về trải nghiệm người dùng và độ ổn định. |

## 4. Thiết kế

### ART-1 — Auth Session State Machine (state_machine)

- **Loại:** `state_machine`
- **Requirements:** `REQ-007`, `REQ-001`

States: [LoggedOut, LoggingIn, LoggedIn, AuthFailed]. Transitions: LoggedOut -> LoggingIn (on submit credentials); LoggingIn -> LoggedIn (on mockAPI success, save session_flag); LoggingIn -> AuthFailed (on API error); LoggedIn -> LoggedOut (on logout click or browser close due to sessionStorage usage); Any -> LoggedOut (on API 401/403 response).

### ART-2 — Dynamic Layout Loading Sequence (sequence_flow)

- **Loại:** `sequence_flow`
- **Requirements:** `REQ-006`, `REQ-001`

1. Page Load: Apply CSS '.content-hidden' to #main-content. 2. Parallel Execution: Load header.html into #header-container; Load footer.html into #footer-container. 3. Success Handler: If both loads succeed -> Remove '.content-hidden' from #main-content. 4. Error Handler: If any load fails -> Inject fallback HTML into respective container -> Remove '.content-hidden' from #main-content.

### ART-3 — Sanitized Data Contract (message_schema)

- **Loại:** `message_schema`
- **Requirements:** `REQ-005`, `REQ-002`

All data objects returned from js/api/mockApi.js must be passed through js/utils/sanitizer.js before rendering. Schema: { id: string, title: string (sanitized), description: string (sanitized), user: { name: string (sanitized) } }. Special characters (<, >, &, ", ') in string fields intended for innerHTML must be escaped to HTML entities.

### ART-4 — Component Load Failure Modes (failure_modes)

- **Loại:** `failure_modes`
- **Requirements:** `REQ-006`, `REQ-001`

Failure: 404 Not Found for header/footer.html. Mitigation: Display static text fallback '[Header Missing]' or default nav links hardcoded in JS. Failure: CORS error when loading components. Mitigation: Ensure static hosting serves correct MIME types and CORS headers, or advise running via local server (Live Server) instead of file:// protocol.

### ART-5 — Development Stop Conditions (stop_conditions)

- **Loại:** `stop_conditions`
- **Requirements:** `REQ-001`, `REQ-003`

1. All 4 modules (Auth, Jobs, Search, Profile) pass integration test with MockAPI. 2. No unescaped user input is rendered to DOM (verified by code review). 3. CSP meta tag is present and valid. 4. Layout does not shift visibly on slow network simulation.

### ART-6 — Auth Token Expiry Recovery (recovery_protocol)

- **Loại:** `recovery_protocol`
- **Requirements:** `REQ-007`, `REQ-002`

If an API call returns 401 Unauthorized: 1. Clear local session flag. 2. Redirect user to login page immediately. 3. Display toast message 'Phiên làm việc hết hạn, vui lòng đăng nhập lại'. Do not attempt silent retry more than once to avoid loops.

## 5. Các bước thực hiện

### STEP-1 — Thiết lập cấu trúc thư mục, các file cốt lõi (layout, auth utils, api wrapper) và cơ chế bảo mật CSP/Sanitization để giải quyết rủi ro XSS.

- **Mục tiêu:** Thiết lập cấu trúc thư mục, các file cốt lõi (layout, auth utils, api wrapper) và cơ chế bảo mật CSP/Sanitization để giải quyết rủi ro XSS.
- **Requirements:** `REQ-001`, `REQ-003`, `REQ-004`, `REQ-005`, `REQ-007`
- **Phụ thuộc:** không có
- **Đầu ra bàn giao:** Sơ đồ thư mục hoàn chỉnh, File mockApi.js với lớp bao fetch, File auth.js với logic lưu session ID thay vì token nhạy cảm, Hàm sanitizeHTML() trong sanitizer.js, Meta CSP config
- **Cách xác minh:** Kiểm tra sự tồn tại của các file theo sơ đồ cây. Xác nhận thẻ meta CSP có trong head. Chạy thử hàm sanitizer với input chứa script tag để đảm bảo output đã được làm sạch.
- **Tiêu chí hoàn thành:** Cấu trúc thư mục được tạo ra đúng theo thiết kế, CSP header được thiết lập qua meta tag, Cơ chế sanitization dữ liệu đầu vào được tích hợp vào lớp Utils, Logic đăng nhập chuyển sang lưu session ID ngắn hạn hoặc flag trạng thái thay vì token đầy đủ

### STEP-2 — Triển khai cơ chế tải động header/footer với xử lý lỗi (fallback) và ẩn nội dung chính cho đến khi layout hoàn thiện để giải quyết vấn đề nháy trang.

- **Mục tiêu:** Triển khai cơ chế tải động header/footer với xử lý lỗi (fallback) và ẩn nội dung chính cho đến khi layout hoàn thiện để giải quyết vấn đề nháy trang.
- **Requirements:** `REQ-006`, `REQ-001`
- **Phụ thuộc:** không có
- **Đầu ra bàn giao:** Script layout.js với logic load có xử lý .fail(), CSS class '.content-hidden' để ẩn nội dung chính, Giao diện fallback đơn giản trong HTML
- **Cách xác minh:** Mô phỏng mạng chậm để kiểm tra hiện tượng nháy. Ngắt kết nối mạng hoặc đổi tên file component để kiểm tra cơ chế fallback (hiển thị thông báo lỗi hoặc header mặc định).
- **Tiêu chí hoàn thành:** Nội dung chính (main content) được ẩn bằng CSS cho đến khi sự kiện 'layout-loaded' được kích hoạt, Lệnh jQuery.load() có kèm handler .fail() để xử lý trường hợp thiếu file, Không còn hiện tượng hiển thị trang trống hoặc thiếu header/footer khi load chậm

### STEP-3 — Phát triển module Quản lý việc làm (Đăng việc, Danh sách việc) tích hợp lớp API và Utils đã chuẩn hóa.

- **Mục tiêu:** Phát triển module Quản lý việc làm (Đăng việc, Danh sách việc) tích hợp lớp API và Utils đã chuẩn hóa.
- **Requirements:** `REQ-002`, `REQ-005`, `REQ-008`
- **Phụ thuộc:** không có
- **Đầu ra bàn giao:** Trang danh sách việc làm, Trang đăng việc mới, Module job-utils.js
- **Cách xác minh:** Kiểm tra luồng dữ liệu: Gọi API -&gt; Nhận data thô -&gt; Utils xử lý/format -&gt; Render ra DOM. Đảm bảo không có lệnh fetch trực tiếp trong file HTML/Page script.
- **Tiêu chí hoàn thành:** Dữ liệu việc làm hiển thị đúng từ MockAPI, Form đăng việc gửi dữ liệu thành công qua mockApi, Code tuân thủ quy ước 3 lớp (API/Utils/Page)

### STEP-4 — Phát triển module Tìm kiếm & Lọc việc làm.

- **Mục tiêu:** Phát triển module Tìm kiếm & Lọc việc làm.
- **Requirements:** `REQ-002`, `REQ-005`, `REQ-008`
- **Phụ thuộc:** không có
- **Đầu ra bàn giao:** Trang tìm kiếm việc làm, Module search-utils.js
- **Cách xác minh:** Thực hiện các truy vấn tìm kiếm với từ khóa và bộ lọc khác nhau. Kiểm tra kết quả trả về có được sanitize trước khi hiển thị không.
- **Tiêu chí hoàn thành:** Chức năng tìm kiếm và lọc hoạt động chính xác, Kết quả hiển thị an toàn (không bị inject script)

### STEP-5 — Phát triển module Hồ sơ cá nhân & Nhắn tin cơ bản.

- **Mục tiêu:** Phát triển module Hồ sơ cá nhân & Nhắn tin cơ bản.
- **Requirements:** `REQ-002`, `REQ-005`, `REQ-007`, `REQ-008`
- **Phụ thuộc:** không có
- **Đầu ra bàn giao:** Trang hồ sơ cá nhân, Trang danh sách tin nhắn, Module profile-utils.js
- **Cách xác minh:** Kiểm tra quyền truy cập: Người chưa đăng nhập phải bị redirect về login khi vào trang profile/messages. Kiểm tra hiển thị tin nhắn và hồ sơ.
- **Tiêu chí hoàn thành:** Cơ chế checkAuth() hoạt động chính xác dựa trên session state, Giao diện hồ sơ và tin nhắn hiển thị đúng dữ liệu từ API

## 6. Issues, rủi ro và trạng thái

| ID | Nội dung | Mức độ | Trạng thái | Hướng giải quyết |
|---|---|---|---|---|
| `ISSUE-d239fb96` | Giải pháp lưu trữ token xác thực trong localStorage (như đề xuất trong REQ-007 và approach) tạo ra lỗ hổng bảo mật nghiêm trọng trước các cuộc tấn công Cross-Site Scripting (XSS), đặc biệt khi sử dụng jQuery và tải nội dung động từ các file HTML bên ngoài. | blocking | resolved | Bổ sung lớp bảo mật: (1) Thiết lập Content Security Policy (CSP) header qua meta tag để hạn chế nguồn script/executable; (2) Rà soát và mã hóa mọi dữ liệu hiển thị từ API trước khi render vào DOM để ngăn chặn XSS; (3) Cân nhắc không lưu token dài hạn mà chỉ lưu trạng thái 'đã đăng nhập' và yêu cầu xác thực lại khi thực hiện hành động nhạy cảm, hoặc chấp nhận rủi ro này như một hạn chế của kiến trúc không backend và ghi rõ trong tài liệu. |
| `ISSUE-1b49a27d` | Việc tải header/footer động bằng jQuery.load() sau khi trang HTML đã hiển thị sẽ gây ra hiện tượng 'nháy' nội dung (layout shift) hoặc hiển thị trang thiếu đầu/cuối trong vài mili-giây, làm giảm trải nghiệm người dùng. | warning | resolved | Cải thiện UX bằng cách: (1) Đặt phần chứa header/footer ở trạng thái ẩn hoặc có skeleton loader cho đến khi nội dung được tải xong; (2) Thêm khối xử lý lỗi (.fail()) trong lệnh load để hiển thị thông báo hoặc giao diện dự phòng nếu file component bị thiếu; (3) Cân nhắc nhúng trực tiếp header/footer vào các trang quan trọng nhất (như Landing page) để tối ưu tốc độ hiển thị lần đầu (FCP), chỉ dùng load động cho các trang con ít truy cập hơn. |

## 7. Evidence index

| Evidence ID | Nguồn / locator | Hash | Trạng thái kiểm chứng |
|---|---|---|---|
