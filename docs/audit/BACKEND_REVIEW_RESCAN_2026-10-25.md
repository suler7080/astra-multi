# Re-scan backend — 2026-10-25 (lượt 2)

Phạm vi: `backend/src/astra_multi` theo cây làm việc tại thời điểm quét 2026-10-25.
Phương pháp: quét tĩnh (read/grep/glob) + ruff + git. **Khác với lượt 1 (2026-10-24): không chạy pytest lần nào trong lượt 2, không chạy mutation, không gọi LLM/API thật.**
Mỗi phát hiện dưới đây kèm: (a) bằng chứng trích nguyên văn, (b) lệnh để bạn tự kiểm chứng lại.
Báo cáo lượt 1: `docs/audit/BACKEND_REVIEW.md`. Báo cáo này là file mới, **không sửa file cũ, không sửa mã nguồn**.

---

## 0. Cảnh báo drift cây repo (đọc trước — ảnh hưởng mọi con số)

Hai lượt không chạy trên cùng một cây.

| Bằng chứng | Giá trị |
|---|---|
| HEAD | `5fea03d 2026-10-13` (không đổi giữa 2 lượt) |
| `git status --porcelain=v1` ngày 24-10 (trước báo cáo) | 49 dòng, SHA256 `4683B5C68AB5E9BD519C8CCDD45DCF0C12EA6D49A589CC8AFEDDE518F7337CC4` |
| `git status --porcelain=v1` ngày 25-10 (hôm nay) | 100 dòng, SHA256 `30E3F21A998341409CCAF63630FA2A9EE08F51BDE6B25C489B44479E3485659C` |
| `graph.py` mtime | **2026-10-24 23:08:50** — sau khi báo cáo lượt 1 được chốt (20:52:37) |
| Các file backend lõi khác (worker, sqlite, budget, models, bundle, verifier, finalization, app, schemas,cli, model_gateway) | mtime 2026-10-14/15 — không đổi sau review |
| `BACKEND_REVIEW.md` tại root | **KHÔNG còn** — đã chuyển & staged: `A  docs/audit/BACKEND_REVIEW.md` |
| File legacy staged-delete (`D`) | `demo.py`, `fake_model.py`, `p2_demo.py`, `persistence_demo.py`, `workflow.py`, `sandbox/runner.py`, `gateway/fake.py`, `gateway/capabilities.py`, `context/evidence.py`, `context/snapshots.py`, `persistence/bridge.py`, `tools/__init__.py`, `tools/broker.py`, `tools/contracts.py`, `tools/documents.py` + 10 test (trong đó có `tests/recovery/test_invariants.py`, `test_crash.py`, `test_recovery.py`, `test_sandbox.py`, `test_snapshots.py`, `test_checkpoint.py`, `test_recovery.py`, `test_workflow.py`) |
| File mới untracked (`??`) trong src | `orchestration/contract_extractor.py`, `orchestration/rubric_checker.py`, `orchestration/technical_grounding.py`, `sandbox/verifier.py` + 6 test mới |
| `backend/uv.lock` | staged-delete |

**Hệ quả:**
1. Con số "ruff src: 15 F401 / 8 I001 / 4 F821 / 1 F841" và "550 passed / 14 skipped" trong báo cáo lượt 1 là của ngày 24-10; hôm nay ruff src còn **23 lỗi (12 F401 / 7 I001 / 4 F821)** — phần giảm nằm ở các file đã xóa, chưa có bằng chứng cho phần tăng/giảm do edit `graph.py`.
2. Baseline pytest **không còn phản ánh suite hiện tại** (mất các test recovery/sandbox/checkpoint).
3. Findings trong báo cáo lượt 1 trích `graph.py` ở dòng đã trôi: F821 1373/1388 → hôm nay 1369/1384; gate None-leniency :1505 → hôm nay :1501. Các phần còn lại của graph.py được pin lại hôm nay (xem mục 3, 4).

Kiểm chứng:

```powershell
git -C "D:\Astra multi" log -1 --format="%h %ad" --date=short
git -C "D:\Astra multi" status --porcelain=v1 | Measure-Object -Line
git -C "D:\Astra multi" status --porcelain=v1 | Select-String "^D "
Get-Item "D:\Astra multi\backend\src\astra_multi\orchestration\graph.py","D:\Astra multi\backend\src\astra_multi\api\worker.py" | Select-Object LastWriteTime, FullName
Get-Item "D:\Astra multi\BACKEND_REVIEW.md" -ErrorAction SilentlyContinue
```

---

## 1. THỪA

### Đã xử lý đúng (so với lượt 1)
Toàn bộ file nghi ngờ "thừa" của lượt 1 hiện **không tồn tại** (glob toàn repo = 0 kết quả, trùng với danh sách `D` ở mục 0): `workflow.py`, `fake_model.py`, `demo.py`, `p2_demo.py`, `persistence_demo.py`. Docstring test xác nhận: `test_storage.py:322` — *"Command sequence formerly provided by the (removed) persistence_demo module."*

**Kiểm chứng:** `Get-ChildItem "D:\Astra multi" -Recurse -Include workflow.py,fake_model.py,persistence_demo.py,demo.py -ErrorAction SilentlyContinue`

### Còn lại: import chết (F401 ×12)
`ruff check src --select F401 --output-format concise` (output nguyên văn):

```
src\astra_multi\api\app.py:44:5: F401 [*] `astra_multi.exports.finalization.SemanticReviewAssessment` imported but unused
src\astra_multi\gateway\model_gateway.py:4:36: F401 [*] `dataclasses.field` imported but unused
src\astra_multi\gateway\model_gateway.py:7:33: F401 [*] `pydantic.Field` imported but unused
src\astra_multi\orchestration\rubric_checker.py:13:8: F401 [*] `re` imported but unused
src\astra_multi\orchestration\rubric_checker.py:21:5: F401 [*] `astra_multi.domain.models.Requirement` imported but unused
src\astra_multi\orchestration\technical_grounding.py:22:5: F401 [*] `astra_multi.domain.models.ID` imported but unused
src\astra_multi\orchestration\technical_grounding.py:26:5: F401 [*] `astra_multi.domain.models.PlanRevision` imported but unused
src\astra_multi\sandbox\verifier.py:22:8: F401 [*] `re` imported but unused
src\astra_multi\sandbox\verifier.py:31:5: F401 [*] `astra_multi.domain.models.ID` imported but unused
src\astra_multi\sandbox\verifier.py:32:5: F401 [*] `astra_multi.domain.models.ArtifactRef` imported but unused
src\astra_multi\sandbox\verifier.py:50:5: F401 [*] `astra_multi.orchestration.technical_grounding.extract_task_full_text` imported but unused
src\astra_multi\sandbox\verifier.py:51:5: F401 [*] `astra_multi.orchestration.technical_grounding.is_negated_or_prohibition` imported but unused
```

Tổng ruff src hiện tại (nguyên văn `--statistics`): **12 F401, 7 I001, 4 F821 = 23**.

**Kiểm chứng:**
```powershell
& "D:\Astra multi\backend\.venv\Scripts\python.exe" -m ruff check "D:\Astra multi\backend\src" --statistics
& "D:\Astra multi\backend\.venv\Scripts\python.exe" -m ruff check "D:\Astra multi\backend\src" --select F401 --output-format concise
```

### Các ứng viên "thừa" đã TRA VÀ BỊ LOẠI (không thừa)

| Ứng viên | Bằng chứng | Kết luận |
|---|---|---|
| `get_attempt_traces` (model_gateway.py:128) | src 0 caller, nhưng tests dùng: test_gateway_retry.py:85, :89, :199 (`assert len(gateway.get_attempt_traces()) == 2`…) | API trace có test — giữ |
| `estimate_call_tokens_and_cost` (graph.py:152) | Đang gọi tại graph.py:288 (`dyn_tokens, dyn_cost = estimate_call_tokens_and_cost(`) | Đang dùng |
| `provider_cli.py` | test chạy subprocess `-m astra_multi.provider_cli` (test_provider_settings.py:481–487) | Có test — giữ |
| `provider_smoke.py` | docstring :1 *"Small opt-in live smoke..."*; `main()` argparse :21–30, 0 tham chiếu từ src/tests | Công cụ vận hành opt-in (việc giữ/bỏ là quyết định chủ đích, không phải dead-code) |
| Dep `keyring==25.6.0` | credentials.py:5 (`import keyring`) | Dùng |
| Dep `cryptography>=42` | security/crypto.py:13 (`from cryptography.fernet import Fernet`) | Dùng |
| Dep `uvicorn` | cli.py:455 (`import uvicorn`), :461 (`uvicorn.run(...)`) | Dùng |

**Kiểm chứng deps:**
```powershell
rg -n "keyring|cryptography|uvicorn" "D:\Astra multi\backend\src"
rg -n "get_attempt_traces" "D:\Astra multi\backend\src" "D:\Astra multi\backend\tests"
rg -n "estimate_call_tokens_and_cost" "D:\Astra multi\backend\src"
```

---

## 2. THIẾU / LỖI LOGIC

### H-1 [MỚI, Medium] SSE stream có 3/4 lối thoát im lặng
`RunWorker.event_stream` (`api/worker.py:304–376`) là `async for` generator với `while True` + polling 0.5s (:307, :376). Có 4 lối thoát:

1. **Đúng, có test pin** — terminal: flush events cuối + gửi `run_completed` + break (:340–372).
2. **Im lặng nhưng BY DESIGN (có test)** — run không tồn tại/bị xóa giữa chừng: `get_run_status_info(run_id)` trả None → `break` không yield gì (:327–330). `tests/integration/test_fix06_sse_lightweight_polling.py:111–120` pin chính xác hành vi này: `async for ev in worker.event_stream("RUN-NONEXISTENT")` → `assert len(collected) == 0`. Vậy lối thoát (2) là chủ đích, không phải bug.
3. **Im lặng, KHÔNG test** — exception trong block kiểm terminal (SQLite OperationalError, json_extract fail…): `except Exception: break` (:373–374).
4. **Im lặng, KHÔNG test** — exception tại `self.store.events(...)` :309 (nằm **ngoài** try): exception thoát khỏi generator → `StreamingResponse` (app.py:455–457) kết thúc connection đột ngột;

Tác động còn lại của H-1 sau khi đối chứng test: **chỉ lối (3) và (4) là chưa có test** — run mất stream giữa chừng khi có exception SQLite trong polling, client không nhận được event lỗi hay `run_completed`. Lối (2) "run không tồn tại" đã được `test_fix06_sse_lightweight_polling.py:111–120` pin là sạch thiết kế. Không mất dữ liệu domain, memory bounded, polling có interval — Medium.

Bằng chứng (nguyên văn worker.py:325–376):

```python
            # Check if run reached terminal status using lightweight query
            try:
                if hasattr(self.store, "get_run_status_info"):
                    status_info = self.store.get_run_status_info(run_id)
                    if status_info is None:
                        break                     # (2) lối thoát im lặng
                    ...
                if status_str in (FINAL, PARTIAL, FAILED, CANCELLED):
                    ...
                    yield {... "run_completed" ...}
                    break                         # (1) lối đúng
            except Exception:
                break                             # (3) lối thoát im lặng

            await asyncio.sleep(0.5)              # (4) events() ở :309 nằm ngoài try
```

Tác động: khi run **còn RUNNING**, client chỉ thấy stream ngắt (EOF) — không phân biệt "ngắt do lỗi backend" với "ngắt bất thường"; không có event lỗi hay `run_completed`. Không mất dữ liệu domain, memory bounded, polling có interval — vì vậy Medium, không Critical.

**Kiểm chứng:**
```powershell
rg -n "except Exception" "D:\Astra multi\backend\src\astra_multi\api\worker.py"
# đọc worker.py 304–376 và app.py 448–457
```

### Carryover A-1 — vẫn nguyên trên code hiện tại (đã pin lại 25-10)
Ba tầng vẫn dùng ba tập "issue chặn" khác nhau:

| Tầng | Bằng chứng hi-today | Tập tính là chặn |
|---|---|---|
| Semantic review | graph.py:1407–1411 — `i.status not in (RESOLVED, DUPLICATE, REJECTED)` | loại cả REJECTED/DUPLICATE |
| Context bundle | bundle.py:346 — `if issue.status not in {RESOLVED, REJECTED, DUPLICATE}` | idem |
| Gate FINAL | graph.py:1480–1483 — `BLOCKING and i.status != RESOLVED` | **gồm cả REJECTED/DUPLICATE** |
| Validator RULE-ISSUE-001 | quality_validator.py:340 — `BLOCKING and issue.status != RESOLVED` | idem gate |

Hệ quả (như lượt 1): issue bị REJECTED/DUPLICATE vẫn đếm là blocking ở gate/validator ⇒ run PARTIAL "ko thực" và `/finalize` không cứu. Mutation lượt 1 M1 (align chỉ đếm OPEN) SURVIVED — không test bảo vệ. Feed: ngày 25-10 chưa có mutation mới, chỉ pin lại vị trí; transition hợp lệ `OPEN→REJECTED/DUPLICATE` theo lượt-1 pin policies.py:73–75.

**Kiểm chứng:**
```powershell
rg -n "IssueStatus" "D:\Astra multi\backend\src\astra_multi\orchestration\graph.py" | Select-String "not in|!="
rg -n "RESOLVED|DUPLICATE|REJECTED" "D:\Astra multi\backend\src\astra_multi\persistence\domain" # không — đúng path:
rg -n "IssueStatus\.(RESOLVED|DUPLICATE|REJECTED)" "D:\Astra multi\backend\src\astra_multi"
```

### Carryover C-2 — `/resume` mất `max_rounds` (pin lại hôm nay)
- Tạo run: app.py:328 — `worker.start_run(run_id, max_rounds=payload.max_rounds)`; payload có trần schemas.py:30 — `max_rounds: int = Field(default=2, ge=1, le=10)`.
- Resume: app.py:693 — `worker.start_run(run_id)` (không truyền) → luôn dùng default 2 ở worker.py:52 (`def start_run(self, run_id, max_rounds: int = 2)`).
- CLI `create` không có flag `--max-rounds` (rg 0 matches trong cli.py) → không có lỗ hổng bound từ CLI; nhưng `/resume` không thể khôi số vòng của run gốc (>2 bị cắt).

**Kiểm chứng:**
```powershell
rg -n "start_run\(" "D:\Astra multi\backend\src\astra_multi\api"
rg -n "max_rounds" "D:\Astra multi\backend\src\astra_multi\api\schemas.py" "D:\Astra multi\backend\src\astra_multi\cli.py"
```

### Carryover C-3 — semantic review swallow + lệch hướng None (pin lại, dịch dòng)
- `save_semantic_review` (sqlite.py:400–414): cả 2 khối (set_setting và file artifact) đều `except Exception: pass`; thêm khối delete ở :393–398 cũng `pass`.
- Gate coi thiếu assessment là "lành": graph.py:1501 — `if sem_assessment and not sem_assessment.passed:` (dịch từ :1505 lượt-1). Mutatmutation lượt-1 M4b (gate None→strict) SURVIVED — không test.
- Ngược lại finalize coi None là fail (finalization.py:146–149) — M4 KILLED, có test pin.

**Kiểm chứng:**
```powershell
rg -n "except Exception:" "D:\Astra multi\backend\src\astra_multi\persistence\sqlite.py"
# đọc sqlite.py 390–414, graph.py 1495–1505, finalization.py 143–152
```

### Hạn chế phòng bị vừa mới giảm
Các test recovery vừa được staged-delete (mục 0) từng là 1/4 killer của mutation budget M3 (lượt 1: `tests/recovery/test_invariants.py::test_concurrent_budget_reservations_race_condition`). Hôm nay killer này có bằng chứng **đã xóa** — phần bảo vệ trần token/cost còn lại: test_budget_and_controller.py, test_p52_enhancements.py ×2 (tồn tại, không nằm trong danh sách D). Chưa xác minh các test mới untracked (test_intake_contract_and_gate.py, test_phase5_finalization_gate.py…) có phủ vùng đó không — xem mục 6.

### Nit (không xếp hạng)
- graph.py:1493 — chuỗi problems **tiếng Việt** ở giữa danh sách tiếng Anh: `f"Còn {len(open_warnings)} issue mức warning chưa giải quyết ({', '.join(open_warnings)})"`.
- schemas.py:68 (`max_rounds: int = 2` không `ge/le`) là trường của **response** DTO (các field kế :55–69 là revision/created_at/stop_reason/counters) — không phải đầu vào, không phải bug.

**Kiểm chứng:** đọc schemas.py 40–78; rg `start_run(` app.py.

---

## 3. BUG

### B1 = H-1 (mục 2) — bug runtime của SSE duy nhất phát hiện hôm nay.

### B2 [latent] F821 `RequirementVerdict` tại graph.py:1369, 1384
`ruff --select F821` (nguyên văn):

```
src\astra_multi\orchestration\graph.py:1369:31: F821 Undefined name `RequirementVerdict`
src\astra_multi\orchestration\graph.py:1384:28: F821 Undefined name `RequirementVerdict`
src\astra_multi\persistence\sqlite.py:400:61: F821 Undefined name `Any`
src\astra_multi\persistence\sqlite.py:416:51: F821 Undefined name `Any`
```

- graph.py:1369 — chỉ là type annotation (`merged_verdicts: list[RequirementVerdict] = []`): vô hại cùng `from __future__ import annotations`.
- graph.py:1384 — **biểu thức runtime** trong nhánh else:
  ```python
              elif rubric_v:
                  chosen_v = rubric_v
              elif model_v:
                  chosen_v = model_v
              else:
                  chosen_v = RequirementVerdict(     # :1384 — NameError nếu chạm
  ```
  Nhánh này **không thể chạm hiện tại**: `evaluate_semantic_rubrics()` duyệt `for req in task.requirements` (rubric_checker.py:41) và append verdict ở mọi nhánh (:63, :94, :111, :138, :164, :185, :205, :217, return :227) → `rubric_by_req.get(rid)` (:1372) luôn non-None cho mọi requirement. Kết luận: **dead code latent** — NameError chỉ xảy ra nếu tương lai coverage của rubric hụt requirement. (Lượt-1 đã chốt same, Medium.)
- sqlite.py:400/:416 — `assessment: Any` / `-> Any` là annotation; không runtime (cần `from __future__ import annotations` — kiểm bằng lệnh dưới).

Đề xuất nhỏ: import đúng hoặc xóa nhánh else; không sửa trong khung review này.

**Kiểm chứng:**
```powershell
& "D:\Astra multi\backend\.venv\Scripts\python.exe" -m ruff check "D:\Astra multi\backend\src" --select F821 --output-format concise
rg -n "from __future__ import annotations" "D:\Astra multi\backend\src\astra_multi\persistence\sqlite.py"
rg -n "for req in task.requirements" "D:\Astra multi\backend\src\astra_multi\orchestration\rubric_checker.py"
```

### Đã soát — KHÔNG phải bug
| Điểm nghi | Kiểm | Kết luận |
|---|---|---|
| So sánh `expires_at` lease kiểu gì? | models.py:31–41 (`utc_now` tz-aware; `UTC = Annotated[datetime, AfterValidator(_utc)]`); ghi sqlite.py:322 `lease.expires_at.isoformat()`; đọc lại sqlite.py:277–279 qua `Lease(...)` (pydantic parse ISO); so sánh :285 (`<= self.clock()`) và :311 (`fromisoformat(row[1]) > now`) | Hai phía tz-aware UTC — nhất quán, đúng |
| crypto.py:127/:136 `except Exception: return None` | verify_access_token fail-*closed* — đúng chuẩn token/auth | Không phải bug |
| `_commit_with_retry` có vòng chồng mới? | budget.py:129–163: `for attempt in range(max_retries=15)`, backoff `0.005 * 2 ** min(attempt, 5)`, raise RuntimeError sau khi deplete :160–163 | Bounded |
| sqlite connect robust? | sqlite.py:64–80: `isolation_level=None, timeout=10`, PRAGMA `foreign_keys=ON/WAL/synchronous=FULL` | OK (ping lại lượt-1, file mtime không đổi) |

---

## 4. VÒNG LẶP VÔ TẬN — KHÔNG PHÁT HIỆN

Toàn bộ `while`/`for` retry trong src: **10 vòng thật** (sau khi loại comment/False hit). Bảng tiến triển:

| # | Vị trí | dạng | Bằng chứng kết thúc |
|---|---|---|---|
| 1 | models.py:457 | topo plan graph | `ready` trống → `raise ValueError("step dependency cycle")` :459–460; mỗi iter xóa các ready nodes (shrink) |
| 2 | quality_validator.py:173 | topo RULE-DAG | `ready` trống → append violation + break :174–181 |
| 3 | quality_validator.py:310 | DFS ancestors | `stack.pop()` 1/iter :311; push điều kiện `curr_dep not in ancestors` :312–314 ⇒ mỗi node pop ≤1 lần |
| 4 | graph.py:1078 | tìm DEC-id trống | `while f"DEC-{dec_counter}" in existing_dec_ids: dec_counter += 1` — counter chỉ tăng :1079–1082 |
| 5 | bundle.py:429 | cắt repo_map | `while repo_map and token>max: repo_map.pop()` — list có giới hạn |
| 6 | bundle.py:450 | minimize issues | `if count(test) <= max or cap == 1: ... break` :455–458; `cap //= 2` :459 ⇒ ≤ log2(n) iters |
| 7 | bundle.py:519 | binary search | chuẩn `low<high`: `low = middle` / `high = middle−1`, bất biến chuẩn ⇒ low==high |
| 8 | model_gateway.py:205 | retry LLM | `while attempt < max_attempts` (по lượt-1 pin: ×3) |
| 9 | budget.py:140 | retry commit | `for attempt in range(max_retries)`, max_retries=15 :134; raise :160–163 |
| 10 | worker.py:307 | SSE polling | 4 lối thoát (mục 2 H-1) — không vô tận tĩnh, nhưng 3 lối im lặng |

Main graph loop: trần kép của lượt-1 (mặc định 2 vòng; API cap `ge=1 le=10` schemas.py:30; CLI không trần thêm; `recursion_limit=150` worker) — unchanged.

**Kiểm chứng (đếm vòng):**
```powershell
rg -n "\bwhile\b" "D:\Astra multi\backend\src\astra_multi" --glob "*.py"
```

---

## 5. TỔNG HỢP LƯỢT 2 (so nguyên trạng với lượt 1)

| Khía | Hi-hôm-nay | So lượt 1 |
|---|---|---|
| Phần thừa | chưa còn legacy tree như ngày 24-10 | legacy đã staged-delete; còn F401 ×12, I001 ×7 |
| Lỗi logic / thiếu | thêm H-1; vẫn A-1, C-2, C-3 | +1 |
| Bug | H-1 runtime + F821 graph.py:1384 latent | +1 runtime, +0 hoan cảnh (F821 còn lại từ lượt 1) |
| Loop vô tận | không có | không đổi |
| Test profile | 490/5/0 — recovery/killers mất một phần | 550/14 (24-10) |
| Live third-party | 2/3 model PASS đủ scenario; longcat = 503 relay | chưa có (mới) |
| Critical | 0 | 0 |

## 6. KHÔNG KIỂM CHỨC ĐƯỢC

1. **[ĐÃ KIỂM CHỨNG — chạy lại 25-10]** Suite trên cây hiện tại, lệnh `python -m pytest tests -q --tb=no -rf -rs` (venv repo, không API key): **490 passed / 5 skipped / 0 failed, 41.09s**.
   - 5 skip: 4 test live provider (test_providers.py:88, :101 — `OPENAI_API_KEY`; :117, :129 — `GOOGLE_API_KEY`) + 1 test lịch sử (test_test7_phase1_behavior.py:29 — thiếu DB runtime).
   - `test_api_serves_frontend` **PASS** trên repo gốc (lần "failed" của lượt 1 chỉ là artifact bản sao thiếu `frontend/`); test live sandbox không còn trong suite (file đã xóa ở mục 0).
   - Suite 550→490 đối ứng danh sách xóa ở mục 0 — **không test fail mới nào**.
   - Killer còn tồn tại của mutation M2/M3/M4 (test_orchestration_workflow.py — F005, test_budget_and_controller.py, test_p52_enhancements.py ×2, test_phase1_finalize_semantic_review.py) đều nằm trong nhóm 490 passed — phần bảo vệ vẫn xanh; riêng killer recovery của M3 bị xóa (mục 0).
   - 6 test mới untracked (test_intake_contract_and_gate…, test_sandbox_plan_verifier…) **đã được thu thập và chạy trong 490 passed** (pytest thu mọi `tests/**`), tức code mới rubric_checker/technical_grounding/contract_extractor/verifier có ít nhất smoke coverage xanh.
2. **Nội dung chính xác của edit graph.py**: giữa 2 lượt có tác động không xác định (2 mốc: F821 dịch -4 dòng, khoảng :1087–:1369); không có snapshot byte từ Temp (đã cleanup) và `git diff` đối chiếu HEAD sẽ gộp cả thay đổi trước khi review. Chỉ biết change tồn tại, chưa isolate chi tiết.
3. **Client-side sau EOF**: hành vi frontend (auto-reconnect EventSource, retry `Last-Event-ID`) ngoài phạm vi backend — không run UI test nào.
4. **Coverage chi tiết của các test mới** (untracked): đã chạy xanh trong suite (mục 6.1), nhưng chưa đọc từng file để xác nhận có phủ đúng các vùng còn hở (A-1: REJECTED/DUPLICATE chặn FINAL; C-3-phía-gate None-leniency; verifier timeout).

## 7. Tuyên bố xác minh của khung này

- Trên cây gốc ngày 25-10: **không sửa bất kỳ file nào**; chỉ tạo file báo cáo này.
- Kết quả tool hôm nay: ruff (3 lệnh, exit 1 khi có lỗi được liệt kê — đúng hành vi; nội dung output ghi nguyên văn trong mục 1/3); glob cho legacy files = 0.
- Thí nghiệm/mutation-verified trong lượt 1 là bằng chứng trên bản sao Temp đã xóa sạch, tra cứu qua báo cáo lượt 1; lượt 2 không tái thực hiện.

---

## 8. KIỂM CHỨC LIVE qua third-party OpenAI-compatible (25-10 — gỡ mục "KHÔNG KIỂM CHỨC" lượt-1 §8.1)

Theo quyết định của user: **bỏ qua OpenAI/Google chính thức**, dùng relay `https://api.xkiro.com/v1`. Công cụ: `provider_smoke` (chạy đúng code-path adapter `generate()` providers.py:280–320 như live tests; cùng path `_generate_openai` providers.py:162–212 vì `kind="openai-compatible"` routes :317).
Config: `provider_cli --config <temp>\profiles.json set thirdparty --kind openai-compatible --base-url ... --no-json-mode --key-env ASTRA_LIVE_KEY --env-only` — output nguyên văn: *"Configured thirdparty; API key is not included in provider metadata"*; file chỉ chứa `"api_key_env": "ASTRA_LIVE_KEY", "credential_source": "environment"` — **không có secret nào trên disk**; key chỉ sống trong env các shell call.

### Kết quả (mỗi call: plain_text + json_schema tiêu--)
| Model relay | plain_text | json_schema (prompt-mode, `json_mode:false`) | usage từ response (p+c=total) | latency |
|---|---|---|---|---|
| qwen/qwen3.8-omni-flash:free | **PASS** ("hello" chính xác) | **PASS** (strict dict + validate) | 192+2=194; 278+10=288 | 26.9s (lần đầu) → 3.3s |
| qwen/qwen3.8-max:free | **PASS** | **PASS** | 200+1=201; 286+9=295 | 3.0s / 3.2s |
| meituan/longcat-2.5-preview:free | FAIL ×3 (`error_code UNKNOWN`) | FAIL ×3 | — | 0.48–0.59s (fast-fail) |

### Diagnosis longcat (trai-relay, không phải adapter)
- Probe `/v1/models`: HTTP 200, 97 ids, thiếu `meituan/longcat-2.5-preview:free` (lưu ý: hai id "qwen3.8-*" của user cũng KHÔNG có trong list nhưng route OK ⇒ list relay không đồng bộ 1:1 với routing).
- Bắt HTTP trực tiếp: POST /chat/completions → **503** `{"error":{"message":"A server error occurred. Please try again.","type":"server_error","code":"service_unavailable"}}`; smoke riêng lần 2 vẫn 503. Là lỗi upstream relay tại thời điểm ngang, **không phải lỗi adapter**.
- Adapter fast-fail đúng thiết kế: smoke đặt `max_retries=0` (provider_smoke.py:53); `_classify_error` (providers.py:85–103) có 2 bucket: `RATE_LIMIT` (:91), còn lại `UNKNOWN` (:103) — 503 rơi vào UNKNOWN (nit nhỏ: có thể thêm bucket SERVER_ERROR; không sửa trong khung review).

### Kết luận kiểm chứng

1. **Usage/billing thực qua custom base_url — VERIFIED**: `usage` đọc từ response từng call (providers.py:201–209) và prompt+completion khớp total tuyệt đối ở 4/4 call PASS ⇒ đường "usage thật → settle" của E-1 đã có data thực (càng hơn suớ nghịch OpenAI/Google(request). KHÔNG verified trên OpenAI/Google chính thức — user quyết định bỏ riêng hai nhà cung cấp đó.
2. **Path JSON khi relay thiếu JSON native — VERIFIED**: profile `json_mode:false` → schema truyền bằng system prompt (`_messages`, providers.py:151) và **KHÔNG** set `response_format` (:187–189); 2/2 model oke trả strict dict được validate.
3. **Hành vi khi relay lỗi**: 503 → `ProviderError("UNKNOWN")` chất lượng fast-fail (không treo, không retry vô hạn); usage None trong fail path — đúng record.

### KHÔNG persisted + kiểm tra lại
- Key trên disk: **zero** (profiles.json chỉ tên biến env; report.json không chứa credential — docstring smoke :1).
- Temp dir dùng: `%TEMP%\opencode\astra_live\` (profiles.json + report.json, không để mã key) — đã dọn sau khi ghi section này.
```powershell
Get-Content "$env:TEMP\opencode\astra_live\profiles.json" | Select-String "sk-"
# không tồn tại nếu còn: file không bao giờ có key; nếu dir đã xóa → không path
```
- Lời khuyên riêng (không phải review): key đã đi qua đoạn chat — cân nhắc rotate tại panel của provider sau khi dừng verify.
