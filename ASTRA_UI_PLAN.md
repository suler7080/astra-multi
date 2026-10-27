# Astra Multi: Kế hoạch giao diện mới (hướng B, phong cách Google)

Làm việc trong `D:\Astra multi\frontend` (React 18 + TypeScript + Vite). Không sửa backend. Branch hiện tại: `feat/auth-settings-and-i18n`.

Nguồn thiết kế: canvas "Astra Multi Redesign", cột B (trang chủ lúc chưa kết nối, màn hình phiên đang chạy). Toàn bộ thông số cần thiết đã ghi trong file này, agent không cần mở canvas.

## 0. Hướng dẫn cho agent điều phối

Đọc toàn bộ file này trước. Trước khi giao việc, đọc nhanh `frontend/src` (cấu trúc, `index.css`, các component, cơ chế i18n) để giao đúng tên file. Mỗi subagent dùng `isolation: "worktree"`. Lưu ý khi tạo worktree: `node_modules` dùng junction trỏ về cây gốc (không chạy `npm ci`), và `frontend/dist` bị gitignore.

### Quyết định cần người dùng xác nhận trước khi chạy
1. **Chỉ giao diện sáng** trong đợt này. Giao diện hiện tại là tối, bản B là sáng. Chế độ tối làm sau bằng cùng bộ token (không làm ở đây).
2. **Font:** DM Sans (400/500/700) và Roboto Mono (400/500). Mặc định: cài `@fontsource/dm-sans` và `@fontsource/roboto-mono` để chạy được khi không có mạng (ứng dụng chạy cục bộ). Nếu không muốn thêm dependency: dùng thẻ Google Fonts trong `index.html` và chấp nhận fallback `system-ui` khi offline.
3. **Không thêm thư viện hoạt ảnh** (không framer-motion, GSAP). Mọi chuyển động bằng CSS, cộng tối đa một hook nhỏ dùng IntersectionObserver cho hiệu ứng hiện dần khi cuộn.

### Phân wave

| Wave | Subagent | Prompt | File chính | Ghi chú |
|---|---|---|---|---|
| 0 | Agent-0 | P0 Nền tảng | index.css, index.html, package.json, tiện ích dùng chung | Chạy một mình, merge xong mới sang wave 1 |
| 1 | Agent-1 | P1 Khung và kết nối | Header, ErrorBanner, panel kết nối | song song |
| 1 | Agent-2 | P2 Trang chủ | view trang chủ, danh sách phiên | song song |
| 1 | Agent-3 | P3 Màn hình phiên | PhaseTracker, PlanViewer, Issues, Timeline | song song |
| 1 | Agent-4 | P4 Hộp thoại | Settings modal, NewRunModal | song song |
| 2 | Agent-5 | P5 Rà soát | toàn bộ frontend | chỉ chạy sau khi wave 1 đã merge |

Các agent wave 1 đều có thể chạm `App.tsx`. Quy tắc: chỉ sửa `App.tsx` ở mức đổi import và vị trí dùng component, không đổi logic trạng thái, SSE hay polling. Orchestrator merge từng nhánh một và chạy gate sau mỗi lần merge.

### Gate sau mỗi wave
```powershell
cd frontend
npm run check:i18n      # phải đủ khóa ở cả VI và EN
npx oxlint --deny-warnings
npm run build
```
Sau wave 2, sao chép `frontend/dist` vào nơi backend phục vụ (cây gốc), rồi chạy `cd backend; .\.venv\Scripts\python -m pytest tests -q --tb=short`. Kỳ vọng: 543 passed / 5 skipped / 0 failed (test `test_api_serves_frontend` cần `frontend/dist`).

## Quy tắc chung (mọi subagent)

```
Chỉ sửa trong frontend/, đúng phạm vi prompt. Không refactor logic không liên quan.
Không đổi hành vi: SSE (kể cả listener stream_error), polling 2s, xác thực admin,
gọi API, luồng tạo/hủy/xóa phiên. Chỉ đổi giao diện và chuyển động.
Không thêm dependency ngoài những thứ được nêu trong prompt hoặc quyết định đã chốt.
Mọi chuỗi hiển thị mới: thêm vào CẢ HAI ngôn ngữ Tiếng Việt và English theo cơ chế i18n
hiện có; ưu tiên dùng lại khóa sẵn có khi nội dung giống nhau.
Truy cập: dùng <button>, <a href>, <input> + <label> thật; icon-only có aria-label;
vùng bấm tối thiểu 44px; tương phản chữ >= 4.5:1; trạng thái không chỉ dựa vào màu
(luôn có chữ hoặc biểu tượng đi kèm); giữ focus-visible rõ ràng.
Chuyển động phải tắt khi người dùng bật prefers-reduced-motion.
Layout phải dùng được ở 390px, 768px và 1280px (không cuộn ngang trang).
Sau khi sửa chạy: npm run check:i18n, npx oxlint --deny-warnings, npm run build.
Không được làm xấu hơn baseline (oxlint exit 0, i18n đủ khóa, build exit 0).
Không push, không đụng nhánh main.
Cuối cùng báo cáo: file đã sửa, khóa i18n đã thêm, kết quả ba lệnh trên, và mọi chỗ
bạn phải lệch khỏi đặc tả (kèm lý do).
```

---

## Đặc tả thiết kế (dùng chung cho mọi prompt)

### Màu (khai báo thành CSS variables ở `:root`)

| Token | Giá trị | Dùng cho |
|---|---|---|
| `--bg` | `#FFFFFF` | nền trang |
| `--bg-alt` | `#F8F9FA` | nền các khối xen kẽ, nền trang phiên |
| `--surface-tonal` | `#F1F3F4` | chip trung tính, ô code, nút phụ |
| `--border` | `#E8EAED` | viền thẻ |
| `--border-strong` | `#DADCE0` | viền nút/outlined chip |
| `--text` | `#202124` | chữ chính |
| `--text-2` | `#5F6368` | chữ phụ |
| `--text-3` | `#3C4043` | chữ trên nền tonal |
| `--accent` | `#1967D2` | nút chính, liên kết, tiến độ |
| `--accent-tonal` | `#E8F0FE` | nền chip/nav đang chọn |
| `--accent-on-tonal` | `#174EA6` | chữ trên nền tonal xanh |
| `--error` / `--error-tonal` / `--error-on-tonal` | `#C5221F` / `#FCE8E6` / `#A50E0E` | lỗi, issue OPEN, ngắt kết nối |
| `--success` / `--success-tonal` / `--success-on-tonal` | `#1E8E3E` / `#E6F4EA` / `#0D652D` | đã kết nối, RESOLVED, PASS |
| `--warn` / `--warn-tonal` / `--warn-on-tonal` | `#F9AB00` / `#FEF7E0` / `#7A4F01` | cảnh báo |
| `--purple-tonal` | `#F3E8FD` | chỉ dùng trong nền gradient hero |

Màu của bốn tác nhân: Planner xanh dương, Reviewer đỏ, Synthesizer vàng, Verifier xanh lá (dùng cặp `--x` đậm cho vòng tròn chữ cái và `--x-tonal` cho nền thẻ; chữ cái trên nền vàng dùng `--text`).

### Hình khối
- Bo góc: nút và chip `999px`; thẻ lớn `28px`; panel `24px`; ô con (code, comment) `16px–20px`; hero surface `36px`.
- Đổ bóng cho thẻ nổi: `0 1px 2px rgba(60,64,67,.15), 0 10px 30px rgba(60,64,67,.14)`. Hover thẻ: `0 10px 28px rgba(60,64,67,.16)`.
- Vùng bấm tối thiểu 44px (nút cao 44–52px).

### Chữ
- Font chữ: `'DM Sans', 'Google Sans', system-ui, sans-serif`. Mã và nhãn kỹ thuật: `'Roboto Mono', monospace`.
- H1 trang chủ: `clamp(40px, 6vw, 76px)`, weight 500, letter-spacing `-0.035em`, line-height `1.04`. H1 màn hình phiên: `clamp(30px, 4vw, 48px)`, `-0.03em`.
- H2 khối: `clamp(28px, 3.4vw, 40px)`, 500, `-0.025em`. Tiêu đề thẻ: 22px/500. Chữ thường 16px, chữ phụ 15px. Chip 12–13px/500.
- Số giai đoạn và ID (RUN-…, ISS-…, EV-…): Roboto Mono 12–13px.

### Chuyển động (khai báo một lần trong `index.css`, dùng bằng class)
```css
.rise { animation: rise .8s cubic-bezier(.2,.7,.2,1) both; }
@keyframes rise { from { opacity: 0; transform: translateY(18px); } to { opacity: 1; transform: none; } }
.drift { animation: drift 14s ease-in-out infinite alternate; }
@keyframes drift { from { transform: translate(0,0) scale(1); } to { transform: translate(-26px,20px) scale(1.14); } }
.pulse { animation: pulse 1.8s ease-in-out infinite; }
@keyframes pulse { 0%,100% { box-shadow: 0 0 0 0 rgba(25,103,210,.45); } 50% { box-shadow: 0 0 0 8px rgba(25,103,210,0); } }
.lift { transition: transform .25s cubic-bezier(.2,.7,.2,1), box-shadow .25s; }
.lift:hover { transform: translateY(-4px); box-shadow: 0 10px 28px rgba(60,64,67,.16); }
.pill { transition: background .15s; }
.pill:hover { background: var(--surface-tonal); }
.btn-fill { transition: filter .15s, box-shadow .15s; }
.btn-fill:hover { filter: brightness(.93); box-shadow: 0 1px 3px rgba(60,64,67,.3); }
@media (prefers-reduced-motion: reduce) {
  .rise, .drift, .pulse { animation: none; }
  .lift, .pill, .btn-fill { transition: none; }
}
```
Hiệu ứng thêm (wave 0, hook `useReveal`): phần tử có class `reveal` ẩn nhẹ và trượt lên khi vào vùng nhìn thấy lần đầu (IntersectionObserver, `threshold: 0.15`, chỉ chạy một lần, tắt khi reduced-motion). Dùng cho các khối bên dưới màn hình đầu của trang chủ.

---

## P0. Nền tảng (Wave 0, một agent)

```
Mục tiêu: dựng nền thiết kế mới, chưa đổi bố cục các view.

1. Đọc frontend/src (index.css, main.tsx, App.tsx, components/, cơ chế i18n) và báo cáo
   ngắn: cấu trúc file, tên các component, nơi lưu màu hiện tại, số khóa i18n.
2. Thay hệ màu: khai báo toàn bộ token trong "Đặc tả thiết kế" thành CSS variables ở
   :root trong index.css. Thay giá trị màu cứng cũ (nền navy, xanh phát sáng, gradient,
   hiệu ứng glow/blur kiểu kính) bằng token mới. Giữ nguyên tên class hiện có để các
   component chưa đổi vẫn chạy; chỉ đổi giá trị bên trong. Xóa CSS chết nếu chắc chắn
   không còn nơi dùng.
3. Font: theo quyết định đã chốt (mặc định cài @fontsource/dm-sans và
   @fontsource/roboto-mono, import trong main.tsx với đúng subset latin + vietnamese).
   Kiểm tra dấu tiếng Việt hiển thị đúng ở mọi độ đậm đang dùng.
4. Thêm các class chuyển động trong "Đặc tả thiết kế" (rise, drift, pulse, lift, pill,
   btn-fill) và khối prefers-reduced-motion vào index.css.
5. Viết hook useReveal (src/hooks/useReveal.ts) bằng IntersectionObserver: trả về ref;
   khi phần tử vào vùng nhìn thấy lần đầu thì thêm class "is-visible" rồi ngừng quan sát;
   nếu prefers-reduced-motion thì thêm class ngay. CSS tương ứng: .reveal ẩn nhẹ và
   trượt lên 16px, .reveal.is-visible hiện đủ trong .7s.
6. Thêm các lớp tiện ích dùng chung vào index.css cho: chip (trung tính, accent, error,
   success, warn), nút (fill, outlined, tonal, disabled), thẻ (card, card-tonal),
   khối mã (code-block, nền surface-tonal, Roboto Mono 13px). Đặt tên rõ nghĩa và ghi
   chú ngắn cách dùng ở đầu khối trong index.css để các agent wave 1 dùng lại.
7. Cập nhật <title> và favicon nếu hiện đang dùng icon kiểu lấp lánh; logo mới là vòng
   tròn rỗng (stroke --accent, độ dày 3) kèm một chấm đỏ nhỏ ở góc trên bên phải, dùng
   SVG nội tuyến.
8. Kiểm tra: toàn app vẫn chạy và đọc được (nền sáng, chữ tối) dù bố cục chưa đổi; ba
   lệnh gate xanh. Chụp hoặc mô tả nhanh các màn hình chính để báo cáo chỗ nào còn
   chữ trắng trên nền sáng hoặc ngược lại (wave 1 sẽ xử lý).
```

## P1. Khung và trạng thái kết nối (Wave 1)

```
Phạm vi: Header, thanh điều hướng, nút ngôn ngữ, chip trạng thái máy chủ, ErrorBanner,
và panel "chưa kết nối máy chủ". Dùng token và lớp tiện ích từ P0.

1. Header nền trắng, cao tối thiểu 76px, tối đa rộng 1280px, padding ngang 32px:
   - Trái: logo (vòng tròn + chấm đỏ) cùng chữ "Astra Multi" 22px/500; nav gồm các
     pill "Phiên" và "Cài đặt" (mục đang chọn nền --accent-tonal, chữ
     --accent-on-tonal, aria-current="page"; mục khác chữ --text-2, hover nền
     --surface-tonal).
   - Phải: chip trạng thái máy chủ (role="status"): ngắt kết nối = nền --error-tonal,
     chữ --error, chấm đặc; đã kết nối = nền --success-tonal, chữ --success-on-tonal.
     Nút ngôn ngữ dạng pill viền --border-strong hiển thị tên ngôn ngữ hiện tại và mũi
     tên (giữ nguyên cơ chế đổi ngôn ngữ, bỏ cờ và nhãn "ENG/VN" cũ). Nút "Tạo phiên mới"
     pill nền --accent chữ trắng (khi ngắt kết nối: disabled, nền --surface-tonal chữ
     --text-2). Nút đăng xuất tròn 44px chỉ có icon + aria-label.
   - Bỏ phần breadcrumb/nút "Tất cả phiên (Trang chủ) (0)" dạng monospace; số phiên
     chuyển xuống phần đầu trang chủ (P2).
2. ErrorBanner và banner lỗi chung (GenericErrorInfo, kể cả lỗi stream_error): bỏ dải
   màu cam toàn chiều ngang. Dùng thẻ bo 24px nền --error-tonal, chữ --error-on-tonal,
   icon lỗi, nút đóng, vùng "chi tiết" thu gọn như hiện tại. Không đổi API props.
3. Panel "Chưa kết nối được máy chủ" (thay cho banner cam + nút Thử lại cũ): thẻ trắng bo
   24px có đổ bóng, gồm: tiêu đề 20px/500 kèm chip Offline; câu "Hãy khởi động backend rồi
   bấm Thử lại"; khối mã nền --surface-tonal chứa hai dòng
     cd backend
     .\.venv\Scripts\python -m astra_multi.cli serve --port 8000
   cùng nút sao chép tròn 44px (dùng navigator.clipboard, báo đã sao chép bằng chữ đổi
   thành "Đã sao chép" trong 2 giây, có aria-live="polite"); và một vòng tiến độ SVG 40px
   (stroke --accent, nền --border) đếm ngược theo đúng bộ đếm tự thử lại hiện có, kèm chữ
   "Tự thử lại sau N giây". Không đổi logic thử lại, chỉ đổi cách hiển thị.
4. Chuỗi mới (lệnh khởi động, "Đã sao chép", "Sao chép lệnh") thêm vào cả VI và EN.
```

## P2. Trang chủ (Wave 1)

```
Phạm vi: view trang chủ (Dashboard), cả trạng thái chưa kết nối/trống và trạng thái có
phiên. Dùng token và lớp tiện ích từ P0. Panel kết nối do P1 làm; bạn chỉ đặt nó vào bố
cục.

Trạng thái chưa kết nối hoặc chưa có phiên (first-run):
1. Hero (max-width 1280px, padding 48px 32px 80px, flex-wrap, căn giữa theo chiều dọc,
   gap 48px). Cột trái (flex 1 1 460px, class rise): chip trung tính "Trang chủ · N
   phiên"; H1 "Bảng điều khiển thiết kế kiến trúc" trong đó cụm "thiết kế kiến trúc"
   tô màu --accent; đoạn mô tả 19px màu --text-2; hai nút pill cao 52px: "Thử lại kết
   nối" (nền --accent, icon làm mới) và "Cấu hình nhà cung cấp" (viền, disabled khi chưa
   kết nối). Khi đã kết nối nhưng chưa có phiên: nút chính đổi thành "Tạo phiên đầu tiên".
   Cột phải (flex 1 1 460px, class rise, animation-delay .12s): bề mặt bo 36px, padding
   40px, nền linear-gradient(135deg, #E8F0FE 0%, var(--purple-tonal) 55%, #FEF7E0 100%),
   overflow hidden, có hai vòng tròn mờ trang trí (class drift, blur 46–50px, opacity
   .7–.75, một xanh #C2D7FB, một vàng #FDE7A8, aria-hidden) nằm sau; bên trong đặt panel
   kết nối của P1 (hoặc, khi đã kết nối, thẻ trạng thái "Máy chủ hoạt động" với địa chỉ).
2. Khối "Thiết lập trước khi bắt đầu" (nền --bg-alt, padding 80px 32px, class reveal):
   H2, một câu phụ, rồi ba thẻ (flex 1 1 300px, bo 28px, viền --border, class lift)
   gồm Máy chủ backend, Nhà cung cấp LLM, Phiên làm việc đầu tiên. Mỗi thẻ: vòng tròn
   icon 52px màu tonal (đỏ, xanh, lục), chip trạng thái ở góc phải, tiêu đề 22px/500,
   mô tả. Trạng thái lấy từ dữ liệu thật: máy chủ (Chưa kết nối / Đã kết nối), nhà cung
   cấp (Chưa cấu hình / Đã cấu hình), phiên (Cần máy chủ / Chưa có / N phiên). Dùng lại
   nguyên văn mô tả hiện có trong i18n.
3. Khối "Một phiên chạy qua 11 giai đoạn" (nền --bg, class reveal): H2, câu phụ, 11 chip
   pill (class pill, cao 44px, nền --surface-tonal, số mờ + tên giai đoạn Roboto Mono
   13px), rồi bốn thẻ tác nhân (flex 1 1 240px, bo 28px, nền tonal theo màu tác nhân,
   vòng tròn 44px chứa chữ cái P/R/S/V, class lift): Planner, Reviewer, Synthesizer,
   Verifier với mô tả một dòng (dùng lại văn bản README/i18n hiện có).

Trạng thái có phiên (đã kết nối, N >= 1):
4. Thay danh sách phiên hiện tại bằng một lưới thẻ (flex-wrap, mỗi thẻ flex 1 1 340px,
   bo 28px, viền --border, class lift): ID phiên (mono), mục tiêu 18px/500 (cắt 2 dòng),
   chip trạng thái (Đang chạy = accent tonal kèm chấm pulse, FINAL/PARTIAL/FAILED/
   CANCELLED dùng cặp tonal thích hợp), dòng "Vòng x / y · Giai đoạn NN", thanh tiến độ
   mỏng 6px theo số giai đoạn đã xong (role="img" với aria-label). Bấm thẻ mở phiên như
   hiện tại. Có ô tìm/lọc nếu hiện đã có thì restyle thành pill, không thêm tính năng.
5. Giữ nguyên toàn bộ gọi API, polling và điều hướng. Mọi chuỗi mới thêm vào VI và EN.
```

## P3. Màn hình phiên (Wave 1)

```
Phạm vi: view chi tiết một phiên: PhaseTracker, PlanViewer, danh sách Issues,
Decisions/Evidence, Timeline, cổng chất lượng (P4 gate), nút hủy/xóa. Nền trang
--bg-alt. Dùng token và lớp tiện ích từ P0.

1. Đầu trang (class rise): nút quay lại dạng pill "Tất cả phiên" kèm mũi tên; H1 mục tiêu
   (clamp(30px,4vw,48px)); hàng chip: trạng thái (Đang chạy = accent tonal + chấm pulse),
   "Vòng x / y", ID phiên (mono, viền --border-strong). Bên phải: nút "Hủy phiên" pill viền,
   chữ --error. Giữ nguyên hành vi hủy/xóa và hộp xác nhận hiện có.
2. PhaseTracker thành bộ stepper trong thẻ trắng bo 28px: tiêu đề "Giai đoạn · NN trên 11";
   danh sách ngang cuộn được (overflow-x auto) gồm 11 pill cao 40px (Roboto Mono 12px/500):
   đã xong = nền --accent-tonal, chữ --accent-on-tonal, có icon dấu tích (aria-label
   "Đã xong"); hiện tại = nền --accent, chữ trắng, aria-current="step"; chưa tới = viền
   --border-strong, chữ --text-2. Nối đúng với dữ liệu SSE hiện có.
3. Bố cục hai cột (flex-wrap, gap 28px): trái flex 999 1 520px, phải flex 1 1 340px.
4. PlanViewer (cột trái): tiêu đề "Kế hoạch · bản N" 24px/500 và chú thích "Vùng đỏ nhạt
   là chỗ Reviewer đang phản biện". Mỗi bước kế hoạch là một thẻ (bo 28px, viền --border,
   class lift): chip ID bước (mono) và chip trạng thái (có issue mở = error tonal "N issue
   đang mở"; đã giải quyết = success tonal; chưa phản biện = trung tính); nội dung bước
   19px/500; nếu có issue blocking đang mở: đoạn văn bị phản biện được tô nền
   --error-tonal (bo 6px) và hiện hộp comment bo 20px nền --error-tonal gồm nhãn mono
   "REVIEWER · ISS-xxx · BLOCKING" và nội dung; nếu có quyết định/bằng chứng: chip mono
   (ID quyết định, EV-xxx · tên · PASS màu success tonal); dòng "Phụ thuộc: …" mono.
   Giữ nguyên dữ liệu và chức năng Plan Diff hiện có (chỉ restyle).
5. Cột phải: thẻ "Issue" (mỗi dòng: ID · mức độ mono, chip trạng thái OPEN = error tonal,
   RESOLVED = success tonal, REJECTED/DUPLICATE = trung tính; tiêu đề; issue đã đóng chữ
   --text-2) và thẻ "Cổng chất lượng" (tiêu đề, "x / y đạt", thanh tiến độ 8px bo tròn
   màu --accent với role="img" và aria-label, danh sách tiêu chí mỗi dòng có vòng tròn
   28px chứa icon tích/gạch chéo/gạch ngang + tên + giá trị mono; dòng kết luận trong ô
   --warn-tonal khi chưa đủ điều kiện FINAL). Số liệu lấy từ dữ liệu thật của gate.
6. Các khối còn lại hiện có (Timeline/nhật ký, câu hỏi Human-in-the-loop, Decisions,
   Evidence, xuất bản artifact) restyle theo cùng ngôn ngữ: thẻ trắng bo 28px viền
   --border, tiêu đề 20px/500, chip thay cho nhãn cũ. Không bỏ tính năng nào.
7. Mọi chuỗi mới thêm vào VI và EN.
```

## P4. Hộp thoại (Wave 1)

```
Phạm vi: Settings modal (3 tab: Nhà cung cấp, Phân vai trò, Đổi mật khẩu admin), hộp
thoại thiết lập mật khẩu admin lần đầu và đăng nhập, NewRunModal (tạo phiên mới),
các hộp xác nhận (hủy/xóa). Dùng token và lớp tiện ích từ P0.

1. Khung hộp thoại: nền trắng, bo 28px, đổ bóng lớn, lớp phủ nền rgba(32,33,36,.5) (không
   dùng blur kiểu kính), vào bằng chuyển động rise ngắn (.3s). Giữ nguyên bẫy focus,
   đóng bằng Esc và click nền như hiện có; thêm role="dialog", aria-modal,
   aria-labelledby nếu còn thiếu.
2. Tab của Settings: thanh pill nằm ngang (mục đang chọn nền --accent-tonal), nội dung
   mỗi tab trong các thẻ nền --bg-alt bo 20px.
3. Trường nhập: input cao 48px, bo 16px, viền --border-strong, focus viền --accent 2px;
   label thật phía trên; thông báo lỗi dưới trường màu --error kèm icon. Select và
   dropdown chọn model (nhóm "Mô hình miễn phí") restyle theo cùng kiểu; giữ nguyên
   chức năng quét model, chuyển nhập tay, ghi đè API key theo vai trò, cảnh báo
   Planner/Synthesizer dùng chung model.
4. Thẻ vai trò (Planner, Reviewer, Synthesizer): nền tonal theo màu tác nhân, vòng tròn
   chữ cái, huy hiệu "✓ N models" thành chip success tonal.
5. NewRunModal: các trường mục tiêu/yêu cầu/vòng lặp theo kiểu trên; danh sách yêu cầu
   có nút thêm/xóa dạng pill; nút "Tạo phiên" pill --accent, "Hủy" pill viền. Hai chỗ
   đã có chú thích oxlint-disable và thứ tự khai báo useState (sửa ở đợt trước) PHẢI
   giữ nguyên hành vi: không đưa lại lỗi render-loop hay mất giá trị mặc định khi
   clone phiên.
6. Nút: chính (fill --accent), phụ (tonal), nguy hiểm (viền, chữ --error). Mọi nút cao
   >= 44px, trạng thái disabled có chữ --text-2 trên nền --surface-tonal.
7. Mọi chuỗi mới thêm vào VI và EN.
```

## P5. Rà soát và hoàn thiện (Wave 2, sau khi wave 1 merge xong)

```
Mục tiêu: làm cho toàn bộ giao diện thống nhất và đạt chất lượng trước khi mở PR.

1. Tìm và sửa mọi chỗ lệch: màu cứng còn sót (grep mã hex không thuộc token), font cũ,
   bo góc/đổ bóng không theo đặc tả, nút cao dưới 44px, khoảng cách không theo nhịp 4px.
2. Truy cập: chạy duyệt Tab qua mọi màn hình chính, mỗi phần tử tương tác có focus-visible
   rõ; kiểm tra tương tác bàn phím của stepper, nav, hộp thoại; kiểm tra tương phản các
   cặp chữ/nền tonal; kiểm tra thông báo aria-live (sao chép lệnh, trạng thái kết nối).
3. Chuyển động: xác nhận tất cả hiệu ứng tắt khi prefers-reduced-motion (thử bằng DevTools
   hoặc emulate); không có hiệu ứng gây giật layout (chỉ animate transform/opacity);
   hiệu ứng reveal không làm ẩn nội dung vĩnh viễn nếu JS lỗi.
4. Responsive: kiểm tra 390px, 768px, 1280px cho trang chủ (hai trạng thái), màn hình
   phiên, Settings, NewRunModal: không cuộn ngang trang, header xuống dòng gọn, stepper
   cuộn ngang trong thẻ của nó. Nếu có Playwright dùng được thì chụp ảnh ba cỡ; nếu
   không thì báo cáo rõ là chưa chụp.
5. Dọn CSS chết, ghi chú ngắn đầu index.css mô tả token và lớp tiện ích. Cập nhật mục
   Frontend trong README (mô tả ngắn giao diện mới và cách chạy dev) nếu có nhắc giao
   diện cũ; không đổi phần khác của README.
6. Chạy toàn bộ gate (mục 0), rồi sao chép dist và chạy pytest backend. Báo cáo kết quả
   từng lệnh, danh sách chỗ lệch đặc tả còn lại, và đề xuất việc làm sau (ví dụ chế độ tối).
```

---

## Việc thủ công (người làm, không giao cho agent)

```powershell
# 1. Chạy thử bằng mắt sau khi merge: hai terminal
cd backend; .\.venv\Scripts\python -m astra_multi.cli serve --port 8000
cd frontend; npm run dev        # http://localhost:5173

# Cần thử: (a) tắt backend để xem trạng thái chưa kết nối và nút sao chép lệnh,
# (b) bật backend, cấu hình nhà cung cấp, tạo một phiên và xem stepper/issue/gate,
# (c) mở hộp thoại Settings và NewRunModal (kể cả clone một phiên cũ),
# (d) đổi VI/EN và xem có chuỗi nào thiếu hoặc bị tràn,
# (e) bật "giảm chuyển động" của hệ điều hành và xem hiệu ứng có tắt hết không.

# 2. Trước khi mở PR: xem diff của NewRunModal.tsx và App.tsx kỹ nhất, vì đó là hai nơi
#    có logic nhạy cảm nhất bị chạm.
```
