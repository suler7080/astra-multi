# Astra Multi: Kế hoạch sửa đợt 2 (sau báo cáo thực thi P1-P5)

Làm việc trong repo `D:\Astra multi`, branch `feat/auth-settings-and-i18n`. Baseline hiện tại: pytest 524 passed / 5 skipped / 0 failed, ruff src 0 lỗi.

## 0. Hướng dẫn cho agent điều phối

Đọc toàn bộ file này trước. Ba prompt dưới đây chạm các file khác nhau nên chạy song song được, mỗi subagent dùng `isolation: "worktree"`:

| Subagent | Prompt | File chính |
|---|---|---|
| Agent-A | P6 | graph.py, controller.py, persistence/sqlite.py, tests/ |
| Agent-B | P7 | frontend/src (App.tsx, types.ts, i18n), KHÔNG đụng backend |
| Agent-C | P8 | providers.py, tests/unit/test_provider_error_classification.py |

Lưu ý khi tạo worktree: `frontend/dist` bị gitignore, nên worktree mới sẽ thiếu nó và `test_api_serves_frontend` sẽ fail 404. Copy `frontend/dist` từ cây gốc vào worktree backend trước khi chạy pytest (lần trước đã gặp đúng lỗi này).

Sau khi cả ba xong: merge, chạy pytest + ruff + `npx oxlint --deny-warnings` + `npm run build`, rồi báo cáo tổng hợp (file đã sửa, test đã thêm, kết quả, mục nào bỏ dở và lý do).

## Quy tắc chung (mọi subagent)

```
Chỉ sửa đúng phạm vi được nêu, không refactor hay xóa mã không liên quan.
Đọc kỹ đoạn mã được trích trước khi sửa, vì số dòng có thể đã trôi.
Backend: sau khi sửa chạy
  .\.venv\Scripts\python -m pytest tests -q --tb=short
  .\.venv\Scripts\python -m ruff check src
Không được làm xấu hơn baseline 524/5/0 và ruff 0 lỗi.
Nếu test cũ mâu thuẫn với prompt, DỪNG và báo cáo, không tự sửa test đó.
Không push, không đụng nhánh main.
Cuối cùng báo cáo: file đã sửa, test đã thêm, kết quả kiểm tra.
```

---

## P6. Lỗi lưu semantic review phải đưa run về trạng thái rõ ràng

```
Bối cảnh: ở đợt trước, save_semantic_review (persistence/sqlite.py) không còn nuốt lỗi
set_setting và lỗi ghi file artifact; chúng lan lên caller. Hai nơi gọi ghi:
orchestration/graph.py ~1456-1459 và orchestration/controller.py ~544-546.
Chưa rõ caller xử lý exception đó thế nào. Rủi ro: run kẹt ở RUNNING mãi, hoặc node
graph chết mà không có event lỗi nên UI không biết gì.

Việc cần làm:
1. Điều tra trước, báo cáo ngắn: khi save_semantic_review ném lỗi ở mỗi trong hai
   caller, run kết thúc ở trạng thái nào? Có event lỗi không? Lease/worker có được
   giải phóng không? Dùng một test tạm hoặc đọc mã để xác nhận, đừng đoán.
2. Nếu run kẹt hoặc không có event lỗi: bắt exception tại ranh giới thích hợp (node
   graph hoặc controller), ghi một event lỗi có nội dung rõ (ví dụ
   "semantic review could not be persisted"), và chuyển run sang FAILED qua đúng
   cơ chế transition/policy hiện có. Không tự thêm trạng thái mới. Không nuốt lỗi
   trở lại: phải log bằng logging.exception.
3. Nếu hiện tại đã xử lý đúng rồi (run ra FAILED kèm event): không sửa mã, chỉ thêm
   test khoá hành vi đó.
4. Test mới: monkeypatch set_setting ném sqlite3.OperationalError khi chạy một run
   tối thiểu (dùng provider giả sẵn có trong test) và khẳng định (a) trạng thái cuối
   của run, (b) có event lỗi, (c) không còn lease treo.
5. Việc phụ trong cùng agent vì cùng chạm graph.py: đổi 4 chuỗi tiếng Việt còn lại ở
   graph.py ~1435, 1440, 1442, 1444 (fallback feedback của semantic review) sang
   tiếng Anh, giữ nguyên ý nghĩa. Đã xác nhận không test nào pin các chuỗi này; hãy
   grep lại trước khi đổi.
```

## P7. Frontend nghe event `stream_error`

```
Bối cảnh: backend (api/worker.py event_stream) giờ yield một event type "stream_error"
với data {run_id, message} rồi đóng stream khi có lỗi. Frontend chưa nghe event này,
trình duyệt bỏ qua im lặng, và EventSource tự reconnect nên nếu store lỗi kéo dài thì
vòng reconnect có thể lặp mãi. Polling 2s hiện đang làm backup nên dữ liệu vẫn đúng.

Phạm vi: chỉ thư mục frontend/. Không sửa backend.

Việc cần làm:
1. Đọc frontend/src/App.tsx (khu vực SSE ~357-475) và api.ts, types.ts để hiểu cách
   đang đăng ký listener theo từng event type và cách es.onerror hoạt động.
2. Thêm listener cho "stream_error": đóng EventSource (es.close()) để chặn vòng
   reconnect, đặt trạng thái isSseConnected=false, và hiển thị một thông báo lỗi
   ngắn cho người dùng theo cơ chế thông báo/toast/banner đang có sẵn trong app.
   Không dựng thành phần UI mới nếu đã có chỗ phù hợp.
3. Sau khi đóng stream, polling 2s phải tiếp tục hoạt động như trước (dữ liệu run vẫn
   cập nhật). Xác nhận bằng cách đọc mã, và nếu có khung test frontend thì thêm test.
4. Cập nhật types.ts nếu có union type cho event; thêm chuỗi thông báo vào CẢ HAI
   ngôn ngữ Tiếng Việt và English theo cơ chế i18n hiện có.
5. Kiểm tra: npx oxlint --deny-warnings và npm run build phải sạch lỗi.
   Báo cáo rõ dist đã được build lại hay chưa.
```

## P8. Siết bucket SERVER_ERROR trong phân loại lỗi provider

```
Bối cảnh: providers.py _classify_error (~85-103) có bucket SERVER_ERROR khớp theo
chuỗi con "502/503/504" trong message. Cách này dễ khớp nhầm: message chứa "5030"
hay "1503 tokens" cũng bị xếp là lỗi server.

Việc cần làm:
1. Xem exception từ SDK/HTTP client có mang status code dạng thuộc tính
   (status_code, response.status_code...) không. Nếu có, ưu tiên dùng nó để xác định
   5xx; chỉ dùng message làm phương án dự phòng.
2. Với phương án dự phòng theo message: dùng regex có ranh giới từ, ví dụ
   \b50[234]\b, và giữ các cụm "service_unavailable"/"server error". Đảm bảo không
   trùng với 401/403/429 và các bucket khác, giữ nguyên thứ tự ưu tiên hiện có.
3. Mở rộng tests/unit/test_provider_error_classification.py, giữ nguyên 9 test cũ và
   thêm: (a) "context length 1503 tokens" → KHÔNG phải SERVER_ERROR; (b) "error 5030"
   → KHÔNG phải SERVER_ERROR; (c) 502/503/504 thật → SERVER_ERROR; (d) exception có
   status_code=503 nhưng message không có số → SERVER_ERROR (nếu bước 1 khả thi).
4. Không đổi logic retry trong gateway; chỉ phân loại.
```

---

## Việc thủ công (con người làm, không giao cho agent)

```powershell
# 1. Kiểm tra commit base có lọt file không mong muốn không
git show --stat 25945e8 | Select-String "profiles.json|report.json|\.env|sk-"
git show --stat 25945e8

# 2. Xác nhận không test cũ nào bị sửa hay xóa sau commit base
git diff --name-status 25945e8..HEAD -- backend/tests
git diff 25945e8..HEAD -- backend/tests/integration/test_api.py

# 3. Rotate API key đã đi qua đoạn chat khi chạy live test (panel của provider)

# 4. Trước khi mở PR: cân nhắc tách commit base 25945e8 thành các commit nhỏ
#    (xóa legacy / file mới / sửa graph.py) để người review đọc được.
```
