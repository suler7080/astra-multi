# BÁO CÁO HOÀN THÀNH PLAN — `ASTRA_FIX_PLAN_2.md` (P6 → P8)

> **Ngày thực thi:** 2026-10-25 (19:54 – 20:09 +07) · **Kênh:** branch `feat/auth-settings-and-i18n` (worktree isolation) · **Người phối hợp:** orchestrator + 3 subagent song song
> **Baseline vào việc:** pytest **524 passed / 5 skipped / 0 failed** · ruff `src` **0 lỗi** · oxlint frontend có 2 warning legacy · plan theo `ASTRA_FIX_PLAN_2.md` mục 0.

---

## 0. Tổng tiến độ 3 nhiệm vụ

| # | Prompt | Vấn đề | Trạng thái | Commit | Thời điểm hoàn thành | Tiến độ |
|---|---|---|---|---|---|---|
| 1 | **P6** | Lỗi lưu semantic review có thể để run kẹt RUNNING không trace | ✅ ĐÃ HOÀN THÀNH | `487fc79` | 25-10 **20:07:17** (+07) | **100%** |
| 2 | **P7** | Frontend chưa nghe `stream_error`, EventSource tự reconnect vòng lặp | ✅ ĐÃ HOÀN THÀNH | `3bd2d31` | 25-10 **20:02:32** (+07) | **100%** |
| 3 | **P8** | Bucket SERVER_ERROR khớp substring "502/503/504" dễ nhầm "5030"/"1503" | ✅ ĐÃ HOÀN THÀNH | `e9b47b5` | 25-10 **20:02:05** (+07) | **100%** |

**Kết quả cuối trên cây merged `9435c54`:**
- pytest **543 passed / 5 skipped / 0 failed** (24.25s) = 524 baseline + 17 test P8 + 2 test P6 (P7 không có test framework frontend nên không thêm test).
- ruff `src` **0 lỗi** · `npm run check:i18n` **360/360 khóa** · `npx oxlint --deny-warnings` **exit 0** · `npm run build` **exit 0** (dist root đã build lại `index-ClWEncOW.js`).
- 3 merge **0 conflict**; worktree `p6`/`p7`/`p8` đã dọn; branch `fix/p6`/`fix/p7`/`fix/p8` giữ lại.

---

## 1. Chi tiết từng nhiệm vụ (tiêu chuẩn 4 mục)

### Nhiệm vụ 1 — P6: Lỗi lưu semantic review phải đưa run về trạng thái rõ ràng

- **Yêu cầu khai:** Điều tra TRƯỚC (don't guess) cả 2 caller ghi (`graph.py` node `semantic_review` ~:1457–1460; `controller.py` ~:544–546): exception khi save → run kết thúc trạng thái nào, có event lỗi không, lease có được giải phóng không. Nếu run kẹt/không có event → bắt exception tại ranh giới phù hợp, `logging.exception`, 1 event lỗi nội dung rõ, chuyển run → FAILED qua đúng cơ chế transition/policy hiện có (không thêm status mới, không nuốt lại). Nếu đã xử lý đúng → không sửa mã, chỉ thêm test khóa. Test: monkeypatch `set_setting` ném `sqlite3.OperationalError` chạy run tối thiểu, khẳng định (a) trạng thái cuối, (b) có event lỗi, (c) không còn lease treo. Việc phụ: dịch 4 chuỗi Việt còn lại graph.py ~:1435/:1440/:1442/:1444 → tiếng Anh (grep lại trước khi đổi).
- **Thời gian hoàn thiện:** 25-10-2026 **20:07:17 (+07)** — commit `487fc79` (≈12 phút; job nặng nhất vì có bước điều tra thực nghiệm). Agent-A (session `ses_e8cddc3bbffeiDq47OBQMJFqMJ`, worktree `p6`, branch `fix/p6`).
- **Hoàn thiện cái gì?:**
  - **Kết luận điều tra (thí nghiệm thật, không đoán):** caller qua `RunWorker`: đã đúng sẵn — worker bắt, mark **FAILED** (phase giữ SEMANTIC_REVIEW, `stop_reason = "Execution error: …"`), persist event `transition_run {phase, status: FAILED}`, ghi traceback vào `errors/{run_id}.log`, lease release trong `finally`. Caller qua **invoke trực tiếp** (`app.invoke`): **run KẸT RUNNING**, `stop_reason=None`, **0 event lỗi**, lease giữ — chính là rủi ro cần đóng.
  - **Row đúng ranh giới node** (điểm hợp lưu cả 2 branch nếu bỏ qua delegate `save_semantic_review` và fallback `repository.save_semantic_review`): trong `semantic_review_node` — `logger.exception("Semantic review could not be persisted for run %s")` (không nuốt), nếu run chưa terminal (FINAL/PARTIAL/CANCELLED) → `ctrl.transition_phase(new_phase=…, new_status=RunStatus.FAILED, reason="Semantic review could not be persisted: <Type>: <msg>")` mirror `worker.py:246–265`; inner-if mark lỗi → `logger.warning` và vẫn `raise`; `raise` lại exception gốc để driver thấy — worker re-mark sẽ **idempotent** (early-return cùng phase+status, controller.py:69).
  - Test mới `tests/integration/test_semantic_review_persist_error.py` — **2 test** phủ cả 2 con đường driver: (1) `app.invoke` trực tiếp → status FAILED, phase giữ, `stop_reason` prefix đúng, **đúng 1** event `transition_run {result: {phase: SEMANTIC_REVIEW, status: FAILED}}`, assessment vắng (`get_semantic_review` → None, fail-closed); (2) `RunWorker` → FAILED + event + `errors/{run_id}.log` chứa `sqlite3.OperationalError` + **mọi lease của run có `expires_at <= clock`** (không treo). Failure path xáckraft kích hoạt bằng counter.
  - Bước phụ: 4 chuỗi fallback feedback → English như bảng trong cây (`"All warning-or-higher issues are resolved…"`, `"{n} warning-or-higher issue(s) remain unresolved"`, `"{n} requirement(s) are not PASS (…)"`, `"{n} rubric item(s) are not MET (…)"`); grep xác nhận 5 match còn lại ở `quality_validator.py`/`test_fix03` ngoài phạm vi.
- **Tiến độ đến đâu:** **100%** — 524→526 passed trong worktree; merge sạch; không test cũ nào kháng; không STOP.

### Nhiệm vụ 2 — P7: Frontend nghe event `stream_error`

- **Yêu cầu khai:** Chỉ làm frontend (`App.tsx`, `api.ts`, `types.ts`, i18n) — không backend. Đọc khu SSE (~357–475) hiểu cách đăng ký listener + `es.onerror`; thêm listener `"stream_error"`: `es.close()` chặn vòng reconnect, `isSseConnected=false`, hiện thông báo lỗi ngắn qua cơ chế thông báo/toast/banner đang có (không dựng component mới nếu đã có chỗ); polling 2s phải vẫn chạy sau khi đóng stream (xác nhận bằng đọc mã, thêm test nếu có khung); cập nhật types nếu có union; chuỗi i18n cả VI + EN; gate `npx oxlint --deny-warnings` + `npm run build` sạch; báo cáo dist đã build lại chưa.
- **Thời gian hoàn thiện:** 25-10-2026 **20:02:32 (+07)** — commit `3bd2d31` (≈7 phút). Agent-B (session `ses_e8cddc3b8ffebAZE941WpAr7F0`, worktree `p7`, branch `fix/p7`; `node_modules` dùng junction tới root — KHÔNG `npm ci`).
- **Hoàn thiện cái gì?:**
  - Listener `stream_error` tại `App.tsx` (~:468–490 sau edit, ngay sau khối `customTypes.forEach`, trước `es.onerror`): parse `e.data` (JSON `{run_id, message}`,_MESSAGE lỗi backend đưa vào "View details" thu gọn), **`es.close()` đầu tiên** chặn reconnect + null-guard `eventSourceRef.current === es` (chống đè ref khi effect re-run), `setIsSseConnected(false)`, `setGenericError({message: t('conn_stream_error'), details: backendMessage})`.
  - Cơ chế đã chọn: banner lỗi sẵn có `GenericErrorInfo` (`components/ErrorBanner.tsx:5–11`) + pattern `handleError` — **không dựng UI mới**; không dùng toast "success" (không hợp ngữ nghĩa lỗi).
  - Polling 2s: xác nhận **độc lập bằng đọc mã** — interval nằm trong effect riêng (App.tsx ~:501–519, chọn nhịp `!isSseConnected ? 2000 : isActive ? 2500 : 12000`, không restart via SSE handler) → sau `es.close()` rơi đúng nhịp 2000ms luồng "disconnected" thiết kế sẵn; dashboard polling (:521–535) cũng độc lập.
  - `types.ts`: **không sửa** — xác nhận không có union enum cho event type (type là `string`, listing là mảng `customTypes`); event mức transport không đưa vào feed events.
  - i18n: thêm **1 khóa `conn_stream_error`** cả VI + EN tại anchor sau `conn_reconnected` — EN `"Live stream error. Updates will continue via periodic polling."` / VN `"Lỗi luồng cập nhật trực tiếp. Dữ liệu sẽ tiếp tục được cập nhật định kỳ."` → `check:i18n` **360/360**.
  - Deviate minh bạch (đúng rule "báo cáo rõ"): gate bắt `--deny-warnings` sạch nhưng repo gốc sẵn **2 warning oxlint** ở `NewRunModal.tsx` (:66/:72) — đã verify tồnại nguyên gốc. Xử lý giữ nguyên 100% hành vi runtime: (1) `react(immutability)` — `setErrors` được gọi trước khai báo state → dịch chuyển `useState` lên trước effect (an toàn, nhất quán mọi render); (2) `react(set-state-in-effect)` — effect sync form "cloning" là có chủ ý (comment team) → block-disable cục bộ `// oxlint-disable/enable react/set-state-in-effect` kèm comment giải thích (2 cách "sửa thật" đều đổi hành vi: render-loop risk / mất lần giữ default-value).
- **Tiến độ đến đâu:** **100%** — 3 gate xanh trên worktree VÀ trên cây merged (i18n exit 0, oxlint exit 0, build exit 0); **dist đã build lại: YES** (worktree + root sau merge `e65924a`); frontend không có test framework (package.json không script test, không vitest/jest) — xác nhận đúng plan, không dựng framework mới; 0 STOP.

### Nhiệm vụ 3 — P8: Siết bucket SERVER_ERROR trong phân loại provider

- **Yêu cầu khai:** Xem SDK/HTTP exception có thuộc tính status code không → nếu có ưu tiên dùng cho 5xx, message là dự phòng; fallback message phải regex ranh giới từ (`\b50[234]\b`) + giữ cụm "service_unavailable"/"server error", không trùng 401/403/429, giữ thứ tự ưu tiên; mở rộng `test_provider_error_classification.py` giữ nguyên 9 test cũ + thêm (a) "context length 1503 tokens" → KHÔNG phải SERVER_ERROR, (b) "error 5030" → KHÔNG, (c) 502/503/504 thật → SERVER_ERROR, (d) exception `status_code=503` message không số → SERVER_ERROR (nếu bước 1 khả thi); KHÔNG đổi retry logic gateway — chỉ phân loại.
- **Thời gian hoàn thiện:** 25-10-2026 **20:02:05 (+07)** — commit `e9b47b5` (≈7 phút; nhanh nhất). Agent-C (session `ses_e8cddc3b6ffey2HuQe1O4LMB1F`, worktree `p8`, branch `fix/p8`).
- **Hoàn thiện cái gì?:**
  - **Khảo sát SDK có dẫn chứng file (trong venv):** openai 1.109.1 `APIStatusError` mang `.status_code: int` + `.response` (httpx Response) — `_exceptions.py:84,90`; httpx 0.28.1 `HTTPStatusError.response.status_code` — `_exceptions.py:265–268`; google-genai 1.40.0 `errors.APIError.code: int` (ClientError/ServerError con) — `errors.py:31–52`; `APITimeoutError`/`APIConnectionError` không có status (đúng chất). `_classify_error` nhận exception **nguyên bản không wrap** (providers.py:202–203, :256–257, :331–332) → dùng được duck-typing. Đã verify runtime với exception thật của cả 3 SDK (7/7 đúng bucket, kể cả `-parametrize 401` → AUTH_ERROR, 429 → RATE_LIMIT).
  - `providers.py`: thêm `import re`; `_SERVER_ERROR_PATTERN = re.compile(r"\b50[234]\b")`; helper `_numeric_status(error)` — thứ tự `status_code` → `code` (**int only**, loại `.code: Optional[str]` openai và bool) → `response.status_code`; bucket SERVER_ERROR (vị trí giữ nguyên: sau BAD_REQUEST, trước UNKNOWN) match khi **`500 <= status <= 599` (từ attr)** OR regex ranh giới từ OR cụm "server error"/"service_unavailable". Substring thô "502/503/504" **đã bỏ** → "5030"/"1503" không khớp nữa.
  - Test: file `tests/unit/test_provider_error_classification.py` **9 test cũ giữ nguyên** + **17 test mới** — cover (a) "context length 1503 tokens exceeded" → CONTEXT_OVERFLOW; (b) "error 5030…" & "1503 units…" (×2 parametrize) → UNKNOWN; (c) "HTTP 502 Bad Gateway"/"HTTP 503"/"HTTP 504" ×3 → SERVER_ERROR; (d) fake `_StatusError` với `status_code` ∈ {500,502,503,504,599} ×5 → SERVER_ERROR; + bổ trợ: fake httpx-style `.response.status_code=502` → SERVER_ERROR; attr 400/401/403/404/429 ×5 → không rơi SERVER_ERROR (thứ tự ưu tiên hoàn hảo). Lưu ý minh bạch: ví dụ đầu thử "HTTP 504 Gateway Timeout" rơi bucket TIMEOUT vì chữ "timeout" được check trước — đúng logic ưu tiên; test đúng chữ "HTTP 504".
- **Tiến độ đến đâu:** **100%** — merge fast-forward sạch (524→541 passed ngay sau bước này, ruff 0); gateway/retry không đụng; 0 STOP.

---

## 2. Nhiệm vụ phối hợp

| Việc | Thời gian | Nội dung |
|---|---|---|
| Commit plan + setup worktree | 19:54:53 | Commit `ASTRA_FIX_PLAN_2.md` (`737896a`) → 3 worktree `p6`/`p7`/`p8` (branch `fix/p6`/`fix/p7`/`fix/p8`); copy `frontend/dist` ×3 (bài học wave 1: test `test_api_serves_frontend` cần); **junction `node_modules`** cho p7 (tránh `npm ci` nhiều phút); bằng chứng junction `oxlint.CMD` OK |
| Dispatch 3 agent song song | ~19:55–56 | Mỗi agent Bước 0 bắt buộc = 524/5/0 + ruff 0;leich phạm vi file tách biệt (backend / backend / frontend) |
| Merge + verify trung gian | 20:02–20:08 | `fix/p8` fast-forward `e9b47b5` → pytest 541/5/0 ruff 0 ✓; `fix/p7` merge `e65924a` → gates frontend: i18n 360 ✓, oxlint 0 ✓, build exit 0 + dist root rebuilt ✓, pytest 541 giữ ✓; `fix/p6` merge `9435c54` |
| Verify chốt | ~20:08–09 | pytest **543/5/0** (24.25s), ruff src **0**; 2 việc check chỉ-đọc mục "Việc thủ công" chạy giúp: (1) `git show --stat 25945e8 \| Select-String "profiles.json|report.json|\.env|sk-"` → **0 match** (base commit không lọt file nhạy cảm); (2) `git diff --name-status 25945e8..HEAD -- backend/tests` → **5 file A (thêm mới) + 1 file M (`test_api.py` — đúng là +105 dòng test mới, 0 deletion); 0 file D** — không test cũ nào bị xóa |
| Docs sync + dọn dẹp | sau verify | README badge 524→**543**, "(529 tests)" → "(548 tests)"; xóa worktree p6/p7/p8, giữ branch; file báo cáo này |

## 3. Deviations / quyết định biên (minh bạch)

1. **P7 sửa 2 warning oxlint legacy** (`NewRunModal.tsx`): ngoài phạm vi nghĩa lý, nhưng thuộc thư mục được phép và không sửa thìgate cuối `--deny-warnings` không đạt; cả 3 phương án đều giữ 100% hành vi runtime (1 hồi restruktur khai báo state, 1 suppress có comment đúng vị trí effect có chủ ý). Orchestrator soi diff + chạy lại gate trên cây merged: exit 0.
2. **P6 chọn bắt ở node graph** (không phải controller delegate) vì node là điểm hợp lưu cả 2 branch (có delegate + fallback); mark FAILED idempotent với worker. Chỉ sửa `graph.py` (+44/−8) — `controller.py`/`sqlite.py`/`worker.py` không đụng.
3. **P7 types.ts không sửa**: event type là `string` + mảng `customTypes` (không có union enum) — xác định qua đọc mã, nằm trong scope plan.

## 4. Scoped-out / để user quyết định

1. **"HTTP 504 Gateway Timeout"** — message nào chứa chữ "timeout" sẽ vào bucket TIMEOUT trước server-bucket (thứ tự ưu tiên plan yêu cầu giữ nguyên). Nếu muốn 5xx-status-code thắng cả chữ "timeout" (giàu adapter status code là đủ), cần đổi thứ tự — không làm vì plan quy định "giữ nguyên thứ tự hiện có".
2. **Việc thủ công của plan (5 mục) đã chạy giúp mục 1–2 (kết quả trong bảng §2)** — còn **3 mục cho người:** (3) rotate API key relay đã đi qua chat; (4) cân nhắc tách commit base `25945e8` thành các commit nhỏ trước khi mở PR; (5) mở PR lên `main`.
3. Test file `test_api.py` duy nhất bị M — là append test P3 (+105, 0 del), không phải sửa test cũ.

## 5. Chữ ký xác minh (chạy lại được)

```powershell
cd backend
& ".venv\Scripts\python.exe" -m pytest tests -q --tb=short   # 543 passed, 5 skipped, 0 failed
& ".venv\Scripts\python.exe" -m ruff check src               # All checks passed (exit 0)
cd ..\frontend
npm run check:i18n                                           # 360/360 keys
npx oxlint --deny-warnings                                   # exit 0
npm run build                                                # exit 0
git log --oneline -8                                         # 9435c54 → 737896a (sơ đồ commit bên dưới)
```

**Sơ đồ commit:** `737896a` (plan) → `e9b47b5` (P8) → `3bd2d31` (P7) → merge `e65924a` → `487fc79` (P6) → merge `9435c54`. Không push; `main` vẫn `5fea03d` nguyên trạng.
