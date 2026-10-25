# BÁO CÁO HOÀN THÀNH PLAN — `ASTRA_FIX_PLAN.md` (P1 → P5)

> **Ngày thực thi:** 2026-10-25 · **Kênh thực thi:** branch `feat/auth-settings-and-i18n` (worktree isolation + base commit) · **Người phối hợp:** orchestrator + 4 subagent
> **Nguồn yêu cầu:** `ASTRA_FIX_PLAN.md` (dạng từ re-scan `docs/audit/BACKEND_REVIEW_RESCAN_2026-10-25.md`) · **Quy tắc ràng buộc:** baseline 490/5/0 không làm xấu; phạm vi file đúng; test cũ mâu thuẫn → DỪNG + báo cáo; không push; `main` không đụng.

---

## 0. Tổng tiến độ 5 nhiệm vụ

| # | Prompt | Vấn đề gốc (audit) | Trạng thái | Commit | Thời điểm hoàn thành | Tiến độ |
|---|---|---|---|---|---|---|
| 1 | **P1** | A-1: 4 nơi dùng 2 định nghĩa "blocking issue" | ✅ ĐÃ HOÀN THÀNH | `ddc800e` | 25-10 18:46:23 (+07) | **100%** |
| 2 | **P2** | C-3: gate/finalize lệch về None + nuốt lỗi lưu semantic review | ✅ ĐÃ HOÀN THÀNH | `ddc800e` | 25-10 18:46:23 (+07) | **100%** |
| 3 | **P3** | C-2: `/resume` mất `max_rounds` đã lưu | ✅ ĐÃ HOÀN THÀNH | `fac5178` | 25-10 18:35:57 (+07) | **100%** |
| 4 | **P4** | H-1: SSE thoát im lặng khi exception | ✅ ĐÃ HOÀN THÀNH | `d101803` | 25-10 18:36:50 (+07) | **100%** |
| 5 | **P5** | F821 ×4 + F401/I001 ×19 + chuỗi Việt + bucket SERVER_ERROR | ✅ ĐÃ HOÀN THÀNH | `b5b1e65` | 25-10 18:54:52 (+07) | **100%** |

**Kết quả tổng thể:** pytest **524 passed / 5 skipped / 0 failed** (baseline 490/5/0 → +34 test mới, 0 test cũ gãy) · ruff `src` **0 lỗi** (baseline 23 lỗi) · **0 test cũ bị sửa** · **0 mục bỏ dở** · 3 worktree đã dọn, branch `fix/p1p2`/`fix/p3`/`fix/p4` giữ làm lịch sử.

---

## 1. Chi tiết từng nhiệm vụ (theo tiêu chuẩn 4 mục)

### Nhiệm vụ 1 — P1: Thống nhất định nghĩa "blocking issue" (A-1)

- **Yêu cầu khai:** Tạo MỘT helper duy nhất trong `domain/policies.py` (hằng số tập status đã đóng hoặc hàm); đổi đúng 4 site đang dùng điều kiện status riêng lẻ; chỉ thay phần status, giữ nguyên điều kiện severity của từng nơi; thêm test mới phủ (a) BLOCKING+REJECTED không chặn FINAL, (b) tương tự DUPLICATE, (c) BLOCKING+OPEN vẫn chặn, (d) 4 nơi cho cùng kết quả trên cùng một tập issue. Không tự sửa test cũ.
- **Thời gian hoàn thiện:** 25-10-2026 **18:46:23 (+07)** — commit `ddc800e`. Thực thi: Agent-1 (session `ses_e8d2caa3dffeFHCziXlis022g5`, worktree `a1`, branch `fix/p1p2`); có 1 lần DỪNG round đầu do lỗi môi trường (xem mục 3), round thứ 2 khởi động lại ~18:37 và chốt chỉ ~9 phút sau.
- **Hoàn thiện cái gì?:**
  - `policies.py`: thêm `CLOSED_ISSUE_STATUSES = frozenset({RESOLVED, REJECTED, DUPLICATE})` + `is_open_issue_status()` (chèn sau `ISSUE_TRANSITIONS`, kèm comment thiết kế: OPEN→REJECTED/DUPLICATE là transition hợp lệ theo :72–85).
  - 4 site đổi dùng helper: `graph.py:1411` (semantic review, giữ BLOCKING+WARNING), `graph.py:1483` (gate FINAL, giữ ==BLOCKING), `exports/quality_validator.py:341` (RULE-ISSUE-001, giữ ==BLOCKING), `context/bundle.py:347`. Không đụng các site ngoài phạm vi (graph.py:1187, bundle.py:353, controller.py:208/338).
  - Test mới `tests/unit/test_blocking_issue_definition.py`: **14 test** — cover đủ (a)/(b)/(c) + test parity 4 nơi (gate node qua API công khai, `StructuralQualityValidator.validate` kể cả `unresolved_blocking_issues`, `ContextBuilder.build_context` liên hệ `closed_resolutions` vs `open_issues`) + parametrize 3 open / 3 closed status.
- **Tiến độ đến đâu:** **100%** — 4/4 site thống nhất, tests xanh ngay lần chạy trong worktree (504/5/0 tại mốc P1), đã merge + đối soát diff độc lập; không có mâu thuẫn test cũ nào phát hiện.

### Nhiệm vụ 2 — P2: Gate coi semantic None là FAIL + bỏ nuốt lỗi khi lưu review (C-3)

- **Yêu cầu khai:** Khảo sát trước mọi caller của `save_semantic_review`; mặc định gate coi assessment None là FAIL (giống finalize — quyết định thiết kế user đã xác nhận); nếu có trường hợp None hợp lệ thì xử lý riêng + comment rõ. `sqlite.py`: khối delete của `save_semantic_review` → `logging.warning` (best-effort); 2 khối còn lại (`set_setting`, ghi file artifact) KHÔNG nuốt lỗi. Thêm test: (a) gate None → không FINAL; (b) parity gate vs finalize cho None/failed/passed; (c) lưu thất bại phải raise xuyên qua.
- **Thời gian hoàn thiện:** 25-10-2026 **18:46:23 (+07)** — cùng commit `ddc800e` (P1 xong mới làm P2, tuần tự trong cùng agent/branch đúng yêu cầu plan vì cùng chạm `graph.py`).
- **Hoàn thiện cái gì?:**
  - Khảo sát caller: ghi site = `graph.py:1456–1459` + `controller.py:544–546`; đọc site = graph proxy (gate), `cli.py:366`, `api/app.py:854`. Wiring luôn `revise → semantic_review → gate` (add_edge :1608–1609), **không tồn tại config tắt semantic review**; nhánh duy nhất để gate thấy None là early-return khi không có plan — trường hợp đó gate fail sẵn vì "No plan committed". **Kết luận: không có None hợp lệ** → áp fail-closed + comment giải thích.
  - `graph.py` (khối gate, ~:1508–1516 sau merge): `sem_assessment is None → problems.append("Semantic review assessment not provided")` — cùng chuỗi với `finalization.py:148`; `elif not sem_assessment.passed` giữ nguyên.
  - `sqlite.py`: thêm `import logging` + `logger`; khối delete → `logger.warning(..., exc_info=True)`; khối `set_setting` + khối ghi file → bỏ try/except, lỗi lan lên caller (kèm comment giải thích fail-closed).
  - Test mới `tests/unit/test_semantic_review_gate_parity.py`: **6 test** — gate None fail đúng reason; parity `gate_passed == can_finalize` cho cả 3 trạng thái; monkeypatch `set_setting` ném `sqlite3.OperationalError` → raise xuyên qua; chặn mkdir `semantic_reviews` → `OSError` xuyên qua.
- **Tiến độ đến đâu:** **100%** — cả 3 khối except xử lý đúng vai trò (1 warning + 2 raise); parity gate↔finalize được pin bằng test; suite xanh 510/5/0 sau mục này trong worktree, không test cũ nào kháng.

### Nhiệm vụ 3 — P3: `/resume` khôi phục `max_rounds` đã lưu (C-2)

- **Yêu cầu khai:** Kiểm tra `max_rounds` có được lưu khi tạo run không; `/resume` đọc giá trị đã lưu và truyền vào `start_run`; run cũ không có metadata → giữ default 2; không đổi schema công khai; KHÔNG đụng `event_stream` (vùng của agent khác); test 2 trường hợp (có lưu → nhận đúng; không metadata → nhận 2).
- **Thời gian hoàn thiện:** 25-10-2026 **18:35:57 (+07)** — commit `fac5178` (mốc đầu tiên của wave A; ≈7 phút từ base checkpoint `25945e8` 18:28:49). Agent-2 (session `ses_e8d2caa3cffeANLWzrXXQIwaWu`, worktree `a2`, branch `fix/p3`).
- **Hoàn thiện cái gì?:**
  - Phát hiện `max_rounds` **đã được lưu sẵn** lúc tạo run: `app.py:313–319` ghi `metadata/{run_id}.json` chứa `role_mappings` + `max_rounds` — cùng persistence mà `worker.py:123` fallback và `get_run` (:385) đã đọc.
  - `app.py:687–696`: khối đọc metadata trong `resume_run` (mirror pattern `get_run`: thiếu file/giá trị → 2, guard `isinstance(..., int)`, best-effort try/except).
  - `app.py:704`: `worker.start_run(run_id, max_rounds=max_rounds)` (trước luôn rơi default 2). `worker.py` không bị đụng — đúng ranh giới merge.
  - `tests/integration/test_api.py` +105 dòng: helper `_stage_run_for_resume` + **2 test** — `test_api_resume_passes_saved_max_rounds` (spy `start_run`; tạo max_rounds=5 → resume → nhận **5**), `test_api_resume_without_saved_max_rounds_defaults_to_2` (xóa metadata file → nhận **2**).
- **Tiến độ đến đâu:** **100%** — không cần cơ chế lưu mới, không migration, schema public giữ nguyên; suite 492/5/0 trong worktree; diff đối soát độc lập và merge fast-forward sạch.

### Nhiệm vụ 4 — P4: SSE báo lỗi thay vì im lặng (H-1)

- **Yêu cầu khai:** Chỉ sửa hàm `event_stream` trong `api/worker.py`; bọc mọi truy cập persistence vào try chung; exception → `logger.exception` + yield MỘT event cuối `stream_error` (payload có `run_id` + message ngắn, không lộ stack) rồi return; GIỮ NGUYÊN lối (1) terminal và lối (2) run-không-tồn-tại (pin `test_fix06:111–120`); đọc `frontend/src/api.ts` chỉ để báo cáo; test mới mock `events`/`get_run_status_info` ném lỗi; `test_fix06` phải vẫn xanh.
- **Thời gian hoàn thiện:** 25-10-2026 **18:36:50 (+07)** — commit `d101803` (≈8 phút từ base checkpoint). Agent-3 (session `ses_e8d2caa3bffezHWOxK4HIjdtyt`, worktree `a3`, branch `fix/p4`).
- **Hoàn thiện cái gì?:**
  - 4 lối thoát xử lý đầy đủ: (1) terminal giữ nguyên (flush cuối + `run_completed` + break), (2) `status_info is None → break` giữ nguyên + comment dẫn về fix06, (3) `except Exception: break` cũ → `logger.exception(...)` + yield 1 event `stream_error` (`id = current_seq+1`, `data {run_id, message}` message generic "Event stream terminated due to an internal error.") + return, (4) `store.events()` nằm ngoài try cũ → đưa vào try chung.
  - Gộp 3 khối yield trùng lặp thành helper `@staticmethod _sse_event(ev)` — envelope `id/event/data` giữ nguyên định dạng (pin bằng test); `asyncio.sleep(0.5)` vẫn ngoài try nên `CancelledError`/`GeneratorExit` (BaseException) không được nuốt.
  - Đọc frontend (CHỈ báo cáo): `api.ts:445–448` chỉ build URL SSE; consumer `App.tsx:357–475` liệt kê event type thắng bí → `stream_error` hiện bị browser bỏ im lặng (không crash), `es.onerror` chỉ set `isSseConnected=false`, polling 2s backup data đúng. Lưu ý: EventSource tự reconnect → vòng reconnect có thể lặp cuando store lỗi kéo dài; khuyến nghị thêm listener `'stream_error'` + hiển thị lỗi UI (việc frontend, ngoài plan).
  - Test mới `tests/integration/test_worker_event_stream_errors.py`: **3 test** — `store.events` ném từ lần gọi 2 (replay OK rồi kết thúc đúng 1 `stream_error`, không có `run_completed`); `get_run_status_info` ném (tương tự); happy-path pin envelope + kết thúc `run_completed` bình thường.
- **Tiến độ đến đâu:** **100%** — fix06 cũ giữ xanh (không phải sửa), suite 493/5/0 trong worktree; merge 0 conflict (vùng `worker.py` tách biệt đúng kế hoạch).

### Nhiệm vụ 5 — P5: Lint-zero + latent NameError + SERVER_ERROR bucket

- **Yêu cầu khai:** Fix F821 ×4 bằng import đúng (KHÔNG xóa nhánh else dead-code của graph.py; `Any` sqlite.py chỉ là annotation); chạy `ruff src --fix` cho F401/I001 (19 lỗi) KCN soi diff mỗi symbol, verify side-effect import; chuỗi Việt `graph.py` ~:1493 → tiếng Anh; (khuyến nghị) thêm bucket `SERVER_ERROR` cho `_classify_error` + test 503, check consumer/retry trước khi thêm; mục tiêu ruff src = 0 lỗi và pytest không xấu hơn.
- **Thời gian hoàn thiện:** 25-10-2026 **18:54:52 (+07)** — commit `b5b1e65` (≈7 phút thực thi; dispatched ~18:47–48 sau khi wave A merge xong). Agent-4 (session `ses_e8d1b301dffewHUJM65npxzvPH`) — chạy trực tiếp trên cây chính đã merge (không còn agent song song).
- **Hoàn thiện cái gì?:**
  - F821: `graph.py` — thêm `RequirementVerdict` vào import block sẵn có `from astra_multi.agents.roles import (...)` (đúng isort); nhánh else :1385 GIỮ nguyên theo khuyến nghị audit (dead code latent). `sqlite.py` — thêm `from typing import Any` vào khối stdlib.
  - `ruff --fix` 19/23 lỗi: 12 F401 xóa đúng (đã soi từng symbol; trường `re` của `verifier.py` — usage duy nhất :283 nằm BÊN TRONG f-string template `generate_verification_script` :247, script generated tự `import re` → xóa module-level import an toàn, đã verify độc lập); 7 I001 chỉ sort/reformat import. **Không khôi phục vị nào.** Arbiter: import-smoke các module chính + full pytest.
  - Chuỗi Việt → Anh: `graph.py:1492` (problems.append warnings) + 2 khối comment tiếng Việt wave A (`graph.py` khối C-3 fail-closed, `sqlite.py` comment cleanup) — diff-only, không đổi logic.
  - SERVER_ERROR: check trước consumers/retry — model_gateway bắt theo **exception type** (không theo `.code`), consumer `.code` duy nhất là `provider_smoke.py:81` (chỉ ghi record), không test pin "server error"→UNKNOWN → thêm bucket an toàn vào `providers.py` (sau BAD_REQUEST, trước UNKNOWN; khớp "server error"/"service_unavailable"/"502"/"503"/"504"; không trùng "403").
  - Test mới `tests/unit/test_provider_error_classification.py`: **9 test** — 5 message kiểu 503 relay → `SERVER_ERROR`; 401 → AUTH_ERROR; 429 → RATE_LIMIT; wording lạ → UNKNOWN; redaction secret → `[REDACTED]`.
- **Tiến độ đến đâu:** **100%** — ruff `src` chuyển từ 23 lỗi → **0 lỗi** (exit 0), pytest **524/5/0**; không STOP theo item nào.

---

## 2. Nhiệm vụ phối hợp (không thuộc 5 prompt nhưng cần để plan chạy đến đích)

| Việc | Thời gian | Tiêu chuẩn 4 mục |
|---|---|---|
| Base checkpoint | 18:28:49 | **Yêu cầu kai:** tạo môi trường worktree không clobber trên cây dirty · **Thời gian:** 25-10 18:28:49 — commit `25945e8` · **Hoàn thiện:** commit toàn bộ working tree làm base + tạo 3 worktree (`a1`/`a2`/`a3`) trên `fix/p1p2`/`fix/p3`/`fix/p4` + sanity import · **Tiến độ:** 100% |
| Khắc phục lỗi môi trường worktree | ~18:36–18:37 | **Yêu cầu khai:** xử lý Bước-0 fail của agents · **Thời gian:** 25-10 ~18:37 · **Hoàn thiện:** chẩn đoán `test_api_serves_frontend` fail 404 vì gitignored `frontend/dist` thiếu trong worktree (KHÔNG phải code — ruff worktree đúng 23 lỗi baseline); copy dist từ cây gốc sang cả 3 worktree; xác nhận rule `frontend/.gitignore:11` → commit không dính artifact; test đơn pass trong a1 · **Tiến độ:** 100% — 1 lần DỪNG duy nhất của plan, không phải mâu thuẫn test |
| Merge wave A | 18:37:45 + 18:47:25 | **Yêu cầu kai:** merge `fix/p3`, `fix/p4`, `fix/p1p2` vào cây chính vừa slop cẩn thận vùng `worker.py`/`app.py` · **Thời gian:** `d6cd0c4` 18:37:45 (p3+p4), `2168a67` 18:47:25 (p1p2) · **Hoàn thiện:** 3 merge sạch, 0 conflict; verify trung gian 495/5/0 (sau p3+p4) rồi 515/5/0 (sau p1p2) với ruff giữ 23 · **Tiến độ:** 100% |
| Verify cuối + sync README + dọn dẹp | 18:57:42 | **Yêu cầu khai:** chạy pytest+ruff chốt; cập nhật docs số test; dọn worktree · **Thời gian:** 25-10 18:57:42 — commit `55eaa87` · **Hoàn thiện:** pytest **524/5/0** (23.9s), ruff src **0 lỗi exit 0** (chạy độc lập, không tin báo cáo agent); README badge `tests-524|5`, mốc 529 tests; xóa 3 worktree, giữ 3 branch · **Tiến độ:** 100% |

---

## 3. Sự kiện DỪNG / mâu thuẫn (minh bạch quy tắc 4)

| Sự kiện | Ai | Nguyên nhân | Kết quả |
|---|---|---|---|
| DỪNG tại Bước 0 (round 1) | Agent-1 (P1+P2) | `test_api_serves_frontend` fail 404 — thiếu gitignored `frontend/dist` trong worktree fresh; ruff baseline khớp 23 lỗi xác nhận code chuẩn | ✅ Orchestrator copy dist + resume; suites sau đó ≤ 24s, **không mâu thuẫn test nào xuất hiện cả 4 agent** — quy tắc 4 không kích hoạt thêm |

---

## 4. Scoped-out (nằm ngoài plan — để user quyết định)

1. **4 chuỗi tiếng Việt còn lại trong `graph.py` :1435 / :1440 / :1442 / :1444** (fallback feedback semantic review, vd `"Tất cả issue mức warning trở lên đã được giải quyết..."`) — plan P5 chỉ liệt kê chuỗi ~:1492; đã grep: không test nào pin các chuỗi này (sửa an toàn nếu user muốn).
2. **Frontend chưa nghe `stream_error`** (backend đã yield event; browser bỏ im lặng, polling 2s backup đúng) — đây là việc frontend, ngoài phạm vi plan; khuyến nghị thêm listener + hiển thị lỗi UI.
3. **`meituan/longcat-2.5-preview` 503 relay-side** (phiên audit trước) — giờ đã được bucket `SERVER_ERROR` phân loại đúng thay vì UNKNOWN.

## 5. Chữ ký xác minh (chạy lại được)

```powershell
$env:PYTHONUTF8='1'
cd backend
& ".venv\Scripts\python.exe" -m pytest tests -q --tb=short        # kỳ vọng: 524 passed, 5 skipped, 0 failed
& ".venv\Scripts\python.exe" -m ruff check src                     # kỳ vọng: All checks passed! (exit 0)
git log --oneline -8                                               # 55eaa87 → 25945e8 (chuỗi commit trong mục 1–2)
```

**An toàn:** không push bất kỳ đâu; `main` vẫn `5fea03d` nguyên trạng; mọi thay đổi nằm trên `feat/auth-settings-and-i18n` (tuần tự: `25945e8` → `fac5178` (P3) → `d101803` (P4) → merge `d6cd0c4` → `ddc800e` (P1+P2) → merge `2168a67` → `b5b1e65` (P5) → `55eaa87` (docs)).
