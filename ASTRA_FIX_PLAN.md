# Astra Multi: Kế hoạch sửa backend (từ re-scan 2026-10-25)

Nguồn: `docs/audit/BACKEND_REVIEW_RESCAN_2026-10-25.md`. Làm việc trong `D:\Astra multi\backend`.

## 0. Hướng dẫn cho agent điều phối (orchestrator)

Đọc toàn bộ file này trước. Giao việc cho subagent theo kế hoạch dưới đây, mỗi subagent dùng `isolation: "worktree"` để không đè file nhau. Không tự sửa mã nếu có thể giao cho subagent.

### Quyết định thiết kế đã chốt (người dùng cần xác nhận trước khi chạy)
- Issue có status REJECTED hoặc DUPLICATE KHÔNG chặn FINAL (Prompt 1).
- Gate coi semantic assessment None là FAIL, giống finalize (Prompt 2).

### Phân wave

| Wave | Subagent | Prompt | File chính | Ghi chú |
|---|---|---|---|---|
| A | Agent-1 | P1 rồi P2 (tuần tự) | graph.py, bundle.py, quality_validator.py, policies.py, sqlite.py, finalization.py | P1 và P2 cùng chạm graph.py nên PHẢI cùng một agent, làm P1 xong mới làm P2 |
| A | Agent-2 | P3 | app.py, worker.py (`start_run`), schemas/persistence | chạy song song với Agent-1 |
| A | Agent-3 | P4 | worker.py (`event_stream`) | chạy song song; chỉ sửa trong `event_stream` để dễ merge với Agent-2 |
| B | Agent-4 | P5 | graph.py, sqlite.py, providers.py, model_gateway.py, app.py | CHỈ chạy sau khi wave A đã merge xong, vì chạm lại các file của wave A |

Sau mỗi wave: merge các worktree, chạy pytest + ruff trên cây đã merge, xử lý xung đột (nếu có) rồi mới sang wave tiếp. Kết thúc: báo cáo tổng hợp (file đã sửa, test đã thêm, kết quả pytest/ruff, mục nào bỏ dở và lý do).

## Quy tắc chung (mọi subagent phải tuân thủ)

```
Làm việc trong D:\Astra multi\backend. Chỉ sửa đúng phạm vi được nêu, không refactor
hay xóa mã không liên quan, không đụng frontend/ trừ khi prompt nói rõ.
Trước khi sửa: đọc các đoạn mã được trích dòng, vì số dòng có thể đã trôi nhẹ
(graph.py đã bị sửa sau review). Sau khi sửa: chạy
  .\.venv\Scripts\python -m pytest tests -q --tb=short
  .\.venv\Scripts\python -m ruff check src --statistics
Baseline hiện tại: 490 passed / 5 skipped / 0 failed. Không được làm xấu hơn.
Nếu test cũ khẳng định hành vi cũ mâu thuẫn với prompt, DỪNG và báo cáo, không tự sửa test đó.
Cuối cùng báo cáo: file đã sửa, test đã thêm, kết quả pytest/ruff.
```

---

## P1. Thống nhất định nghĩa "blocking issue" (A-1)

```
Vấn đề: bốn nơi dùng hai định nghĩa khác nhau về "issue đang chặn":
- Semantic review: orchestration/graph.py ~1407 và context/bundle.py ~346 loại cả
  RESOLVED, DUPLICATE, REJECTED.
- Gate FINAL: graph.py ~1480 và exports/quality_validator.py ~340 (RULE-ISSUE-001)
  chỉ loại RESOLVED, nên issue REJECTED/DUPLICATE vẫn bị tính là blocking và run
  bị PARTIAL oan.

Quyết định thiết kế: issue REJECTED hoặc DUPLICATE KHÔNG chặn FINAL (transition
OPEN→REJECTED/DUPLICATE là hợp lệ theo domain/policies.py ~73-75).

Việc cần làm:
1. Tạo một helper duy nhất (ví dụ trong domain/policies.py) kiểu
   is_blocking_issue(issue) hoặc một hằng số tập trạng thái "đã đóng", rồi để cả 4
   chỗ trên dùng chung. Không để mỗi nơi tự viết lại điều kiện.
2. Giữ nguyên điều kiện severity == BLOCKING ở gate/validator; chỉ thay phần status.
3. Thêm test: (a) issue BLOCKING status REJECTED không chặn gate FINAL và không
   vi phạm RULE-ISSUE-001; (b) tương tự với DUPLICATE; (c) issue BLOCKING status OPEN
   vẫn chặn; (d) bốn nơi cho cùng kết quả với cùng một tập issue.
4. Chạy lại toàn suite; nếu test cũ nào đang khẳng định hành vi cũ, báo cáo thay vì
   tự sửa test đó.
```

## P2. Gate và finalize xử lý semantic assessment None khác nhau; nuốt lỗi khi lưu (C-3)

```
Vấn đề:
(a) graph.py ~1501: `if sem_assessment and not sem_assessment.passed:` coi thiếu
    assessment là hợp lệ. Còn exports/finalization.py ~146-149 coi None là fail
    (đã có test pin). Hai nơi mâu thuẫn.
(b) persistence/sqlite.py save_semantic_review (~393-414) có 3 khối
    `except Exception: pass` (delete, set_setting, ghi file artifact), nên lưu thất
    bại mà không ai biết, rồi gate lại thấy None và cho qua.

Việc cần làm:
1. Trước khi sửa, tìm mọi caller của save_semantic_review và mọi nhánh mà graph.py
   có thể bỏ qua semantic review hợp lệ (ví dụ cấu hình tắt). Báo cáo ngắn nếu có
   trường hợp None là hợp lệ, rồi mới quyết định.
2. Mặc định: gate coi assessment None là FAIL, giống finalize. Nếu bước 1 cho thấy
   có trường hợp None hợp lệ, xử lý riêng và ghi chú rõ trong code.
3. Thay `except Exception: pass` bằng: logging.warning/exception cho khối delete
   (dọn dẹp best-effort), còn set_setting và ghi file thì để lỗi lan ra hoặc raise
   một exception có tên rõ nghĩa, không được nuốt.
4. Test mới: (a) gate với assessment None → không FINAL; (b) gate và finalize cho
   cùng kết luận với cùng đầu vào None/failed/passed; (c) lưu thất bại (mock
   set_setting ném lỗi) thì lỗi không bị nuốt.
```

## P3. `/resume` mất `max_rounds` (C-2)

```
Vấn đề: api/app.py ~328 tạo run bằng worker.start_run(run_id,
max_rounds=payload.max_rounds) (schemas.py:30 cho phép 1-10). Nhưng /resume
(app.py ~693) gọi worker.start_run(run_id) không truyền gì, nên luôn rơi về mặc định
2 (worker.py:52). Run gốc cấu hình 5 vòng bị cắt còn 2 khi resume.

Việc cần làm:
1. Kiểm tra max_rounds của run có được lưu ở đâu không (run metadata / settings).
   Nếu chưa, lưu nó khi tạo run, theo đúng cơ chế persistence hiện có, không thêm
   migration nặng nếu có thể dùng chỗ lưu metadata sẵn.
2. /resume đọc max_rounds đã lưu và truyền vào start_run. Run cũ không có giá trị
   đã lưu thì giữ mặc định 2.
3. Không đổi schema request/response công khai trừ khi bắt buộc; nếu bắt buộc thì
   báo cáo.
4. Test: tạo run với max_rounds=5, resume, xác nhận start_run nhận 5; run cũ không
   có metadata vẫn nhận 2.
```

## P4. SSE thoát im lặng khi exception (H-1)

```
Vấn đề trong api/worker.py RunWorker.event_stream (~304-376):
- Lối thoát (3): `except Exception: break` (~373) nuốt mọi lỗi (SQLite
  OperationalError, json_extract...), client chỉ thấy stream đứt.
- Lối thoát (4): self.store.events(...) (~309) nằm NGOÀI try, exception thoát khỏi
  generator và StreamingResponse (app.py ~455-457) cắt connection đột ngột.
Hai lối còn lại (terminal; run không tồn tại, được pin bởi
tests/integration/test_fix06_sse_lightweight_polling.py:111-120) phải GIỮ NGUYÊN
hành vi.

Việc cần làm:
1. Bọc cả lần gọi store.events() trong try. Khi có exception ở bất kỳ lối nào:
   log bằng logging.exception, yield MỘT event lỗi cuối cùng (ví dụ type
   "stream_error", kèm run_id và message ngắn, không lộ stack trace), rồi return.
   Dùng cùng định dạng event như các event hiện có.
2. Không đổi hành vi khi run không tồn tại (vẫn không yield gì) và khi run terminal.
3. Kiểm tra frontend/src/api.ts xử lý event type lạ thế nào. Chỉ báo cáo, chưa sửa
   frontend.
4. Test mới: mock store.events ném lỗi → generator yield stream_error rồi kết thúc;
   mock get_run_status_info ném lỗi → tương tự; test_fix06 cũ vẫn xanh.
```

## P5. Dọn ruff và F821 (chạy sau wave A)

```
Việc cần làm (không đổi logic nghiệp vụ):
1. Sửa F821:
   - orchestration/graph.py:1369 và :1384: `RequirementVerdict` chưa import. Import
     đúng từ domain.models (xác nhận tên nó nằm ở đâu trước). KHÔNG xóa nhánh else.
   - persistence/sqlite.py:400 và :416: thiếu `from typing import Any`
     (kiểm tra xem P2 đã thêm chưa).
2. Chạy `ruff check src --fix` cho F401 và I001, chỉ trên src/. Sau đó đọc diff,
   đảm bảo không xóa import có side-effect hoặc re-export (kiểm tra
   gateway/model_gateway.py và api/app.py trước khi chấp nhận).
3. Tùy chọn nhỏ: trong providers.py _classify_error (~85-103), thêm bucket
   SERVER_ERROR cho HTTP 5xx thay vì rơi vào UNKNOWN. Chỉ làm nếu ErrorCode enum
   thêm được mà không ảnh hưởng nơi dùng; thêm một test cho 503.
4. Đổi chuỗi tiếng Việt ở graph.py ~1493 sang tiếng Anh cho nhất quán với danh sách
   problems xung quanh.
Mục tiêu: `ruff check src` ra 0 lỗi, pytest vẫn 490+ passed.
```
