# BACKEND_REVIEW.md — Kiểm toán độc lập backend Astra Multi

Ngày: 2026-10-24 · HEAD tại thời điểm kiểm tra: `5fea03d82f602df951b5f43746efd79ddbe9da0f` (2026-10-13)
Phạm vi: `backend/` (đúng đắn logic vận hành + tối ưu hiệu năng/chi phí/token). Chỉ phân tích và đo lường — **không sửa mã nguồn**; mọi thí nghiệm mutation thực hiện trên bản sao tạm, đã xóa.

---

## 1. Tóm tắt

- 62 file ~19,200 LOC; lõi `orchestration/graph.py` (1623 dòng). Baseline: **550 passed / 14 skipped** (54.85s), ruff 132 lỗi, mypy 131 lỗi.
- Vòng lặp/phà budget **có trần thật** (gemini kép gate + `should_loop_or_export`, mặc định 2 vòng; `recursion_limit=150`); **không phát hiện lặp vô hạn**.
- **Chưa phát hiện Critical** (vượt ngân sách không kiểm soát / mất dữ liệu domain / ghi bằng lease hết hạn đối tượng). Cách né khẩu nghĩa: fencing epoch chặn ghi lệch; budget reserve chặn call kế tiếp; mỗi vòng có trần.
- **4 FINDING High, 9 Medium** (chi tiết mục 5). Ba chủ đề chính: lệch tập "issue chặn" giữa gate/validator/semantic-review (A-1); cancel không chấm dứt LLM call đang bay (C-1); BudgetExhausted → run FAILED thay vì PARTIAL (E-2).
- **3 điểm "thiếu test bảo vệ" phát hiện bằng mutation** (A-1, C-3-phía-gate, G-2) và 1 điểm được pin cố ý thành thiết kế (B-1).
- Đo lường (mock, không gọi LLM thật): đường persistence chiếm **58% wall** của run (commit 0.526s/0.904s); `state_json` ×16.3 sau 5 vòng (+~300B/revision); prompt/role mỗi call ~0.9–1.15k token và tăng ~10–40 token/vòng sau lần nhảy đầu.
- README.md:250 ghi "477 passed" — **stale** so với 550 thật.

## 2. Baseline

| Tool | Lệnh | Kết quả |
|---|---|---|
| pytest | `python -m pytest tests -rs --tb=no -q` (backend) | **550 passed, 14 skipped, 2 warnings, 54.85s** |
| ruff | `-m ruff check src [--statistics]` | src 28 lỗi (15 F401, 8 I001, **4 F821 undefined-name**, 1 F841); tests 104 |
| mypy | `-m mypy src` | **131 lỗi / 16 file** (62 file checked) |

- **F821/runtime**: `graph.py:1373/1388` dùng `RequirementVerdict` không import (nhánh else ≈ dead-code bình thường vì `evaluate_semantic_rubrics()` luôn gán verdict cho mọi requirement — `rubric_checker.py:41–225`); `sqlite.py:400/416` dùng `Any` không import (`from __future__ import annotations` nên chỉ latent-annotation). Mức **Medium**.
- 14 skips: 6× test_sandbox.py:45 (cần `ASTRA_P2_LIVE_SANDBOX=1`), 4× test_providers (API key), 1× test_test7_phase1_behavior.py:32 (historical run), 3× test_snapshots (POSIX-specific).
- Repo **đã dirty sẵn trước review** (nhiều file M + untracked). Snapshot `git status --porcelain=v1` 49 dòng lưu cùng SHA256 `4683B5C6…F7337CC4`; đối chiếu cuối xem mục 8.

## 3. Bản đồ & luồng

- Hướng import chính: `api → orchestration(5)+persistence(4)`, `orchestration → domain(13)`, `persistence → domain(9)+exports`, `sandbox → orchestration(2)`, `exports → orchestration(1)`.
- Điểm vào: CLI `create` chỉ ghi DB (không chạy graph); execution duy nhất là `POST /api/runs → worker.start_run → RunWorker._execute_run` (lease TTL 300s, heartbeat 30s, `app.invoke` trong executor thread, `recursion_limit=150` — worker.py:212–215).
- State canonical = 1 JSON blob `runs.state_json` + `events` + `operations` + `leases` (migrations.py:5–9).

## 4. Bảng kết luận A–G

| Mục | Hạng mục | Kết luận | FINDING |
|---|---|---|---|
| A | Dừng & vòng lặp | **PASS** — trần kép (graph.py:1535–1536, 1567–1572), intake trần 2 (427–446), stagnation detector (termination.py:28–81) | A-1 **High** |
| B | Issue lifecycle/ID/dedupe | **PASS** về transitions (policies.py:88–166); bundle loại trừ terminal + blocking-first trước truncate (bundle.py:346, 349–350) | B-1 **High**, B-3 Medium |
| C | LLM retry/billing/cancel/resume | **PASS** — retry trần ×3 (model_gateway.py:178), usage thật từ response (providers.py:201–211, 251–263), partial-settle khi lỗi (graph.py:362–386 + model_gateway.py:186–203), fencing giữ dữ liệu (sqlite.py:276–287) | C-1 **High**, C-2/C-3/C-4 Medium |
| D | Concurrency/persistence | **PASS** — epoch/token/owner/expiry re-check trong commit (sqlite.py:276–287), `acquire(force=True)` chỉ ở cancel (app.py:734) | D-1 Medium |
| E | Budget | **PASS** — reserve theo projected (budget.py:186–206), release trong finally (graph.py:384–386), settle theo usage thật (341–360) | E-2 **High**, E-1 Medium |
| F | Quality gate & export parity | **PASS** — RULE-DAG-001..008/COV-001/FULFILL-001/002 (quality_validator.py:59–601); requirements 100%, DAG rỗng không thể pass | F-1 Medium |
| G | Sandbox verify (đường production) | **PASS** — ToolCall/Evidence FAIL/ValidationResult FAIL/Issue BLOCKING đúng header (verifier.py:6–11, 456–474); script gen escaping cấu trúc (252–311) | G-1/G-2 Medium |

## 5. FINDINGS chi tiết

> Mứcudiante: **Critical** = mất dữ liệu / vượt ngân sách không kiểm soát / lặp vô hạn / ghi bằng lease hết hạn. Không mục nào dưới đây đạt ngưỡng Critical (ký lời phi at từng mục).

- **A-1 [High] Ba tầng dùng ba tập "issue chặn"; blocking bị REJECTED/DUPLICATE vĩnh viễn chặn FINAL.** Semantic review loại `{RESOLVED, DUPLICATE, REJECTED}` (graph.py:1414); context bundle cũng vậy (bundle.py:346); nhưng gate đếm `BLOCKING and status != RESOLVED` (graph.py:1486) và validator `RULE-ISSUE-001` tương tự (quality_validator.py:340 — được dùng tiếp bởi `/validate` và `/finalize`, finalization.py:20–24). `OPEN→REJECTED/DUPLICATE` hợp lệ (policies.py:73–75) và terminal không đường mở lại (82–84). Tác động: run end PARTIAL sai sự thật, `/finalize` không cứu. **Mutation M1 (SURVIVED):** align validator chỉ đếm OPEN → **0/550 test phát hiện** → hành vi này không có test bảo vệ.
- **B-1 [High] Trùng lặp issue xuyên vòng/node/sandbox-call (cố ý, được test pin).** `derive_issue_id` nhét `round` vào UUID5 (graph.py:147–150) cùng `node` → cùng nội dung ở vòng sau = ID mới; `existing_issue_ids` (graph.py:712/771, 1288/1347) không cứu xuyên vòng; sandbox hash gồm `call_id` (verifier.py:463). Stagnation coi tăng `total_issue_count` là progress (termination.py:81) → chạy hết trần thay vì dừng sớm. **Mutation M2 (KILLED):** gỡ `round` khỏi UUID → `test_f005_idempotent_nodes_no_duplicate_proposals_or_issues` fail — assertion `len(issues) == 2` (test_orchestration_workflow.py:871) **yêu cầu cùng nội dung round sau phải tạo issue mới** → đây là thiết kế được pin, sửa B-1 đồng nghĩa thay đổi thiết kế + test.
- **B-3 [Medium] Alias `ISSUE-{idx+1}` theo vị trí list:** graph.py:794–796, 1119–1131, 1244–1254 — dịch vị trí khi thêm issue mới có thể trỏ resolution nhầm issue. Có re-check `actual_id` (1114) nên chỉ là nguy cơ.
- **C-1 [High] Cancel không chấm dứt LLM call đang bay.** Cancel route force-steal lease (app.py:702–744; `force=True` :734) + `stop_task` chỉ hủy asyncio task 5s (worker.py:66–83), executor thread chạy `app.invoke` không hủy được (worker.py:212–215). Call đang bay chạy hết và billed; các commit sau `LeaseLost` (sqlite.py:276–287) nên usage chót không ghi state. Không Critical: tổng ngân sách vẫn bị trần chặn.
- **C-2 [Medium] `/resume` mất `max_rounds`:** metadata lưu `max_rounds` (app.py:316–317) nhưng resume gọi `start_run(run_id)` chỉ định không có (app.py:693) → luôn chạy mặc định 2.
- **C-3 [Medium] Semantic review ghi 2 nơi không nguyên tử + nuốt lỗi; gate và finalize lệch hướng về None.** `save_semantic_review` ghi app_settings + file artifact, mỗi khối `except Exception: pass` (sqlite.py:400–414). Gate coi thiếu assessment là "lành" (graph.py:1500–1508), finalize coi None là fail (finalization.py:146–149). **Mutation M4 (KILLED):** flip finalize None→pass → `test_finalize_without_semantic_review_returns_partial` bắt đúng đắn. **Mutation M4b (SURVIVED):** flip gate None→strict → **0 test phát hiện** → bất đối xứng: phía khóa đã được bảo vệ, phía "lành" không.
- **C-4 [Medium] Luồng Q&A chết trong production:** `ask_question` 0 caller trong src; graph không bao giờ đặt `WAITING_FOR_INPUT` (chỉ `/finalize`, finalization.py:240) → `/answers`,`/resume` (app.py:656, 677) không bao giờ nhận được từ graph.
- **D-1 [Medium] Blocking IO trong async event loop:** `list_runs` parse toàn bộ state mỗi run (app.py:342–367); commit read-modify-write full-blob (sqlite.py:207–218); SSE polling 0.5s tại event loop (worker.py:376). *Đo được:* list_runs với 30 run nhỏ = 0.56ms/lần; json.loads 22.7KB = 0.034ms → chi phí tuyến tính nhưng chưa nóng ở quy mô hiện tại.
- **E-2 [High] Hết ngân sách → run FAILED thay vì xuất PARTIAL orderly:** BudgetExhaustedError từ reserve (budget.py:191/198/205) → node raise → worker chỉ SchemaError mới hạ PARTIAL, còn lại FAILED (worker.py:243–262; :262). `StopReason.BUDGET_EXHAUSTED` khai (termination.py:22) nhưng graph không dùng (grep `StopReason.`: chỉ :1524/:1536/:1556). **Mutation M3 (KILLED, 4 test):** vô hiệu trần token/cost → 4 test phát hiện ngay (budget unit, p52 ×2, recovery invariant) → tầng ngân sách được bảo vệ tốt.
- **E-1 [Medium] Settle không kẹp trần + timeout tính theo ước lượng:** settle cộng `actual` vào `used` (budget.py:273–274) → 1 call có actual > ước lượng vượt trần một khoảng (chỉ chặn ở call kế); call timeout tính theo chars/4 (model_gateway.py:167–172, `is_estimated` :33/:184).
- **F-1 [Medium] Parity JSON↔MD không tuyệt đối + escape thiếu:** JSON giữ `issues[].impact`, `steps[].targets/evidence_ids`, `decisions[].evidence_ids`, `evidence[].source_type` mà MD không in (exporter.py:82–127 so 138–268) — trái header "Identical content across formats" (exporter.py:5–7). `escape_markdown` chỉ escape `<`/`>` (exporter.py:17–25) — `|` từ LLM làm vỡ bảng.
- **G-1 [Medium] Verify subprocess dùng env đầy đủ + output không redact:** `env=dict(os.environ)` (verifier.py:328–338); output không qua redaction. Contrast: `sandbox/runner.py` có redaction/kill-tree nhưng chỉ dùng bởi demo/tests (grep), không thuộc đường production.
- **G-2 [Medium] Timeout subprocess không kill-tree (Windows) + không truyền cancel:** verifier.py:332–343; **Mutation M5 (SURVIVED):** `timeout=None` → **0 test phát hiện** (6 test live Docker NOT_RUN) → verify chạy vô hạn không có ranh giới test.

## 6. Đo lường (Giai đoạn 3 — mock, venv gốc, bản sao tạm)

**Prompt bloat 5 vòng** (`scripts/measure_prompt_bloat.py`, fixture Minesweeper, token = chars/4):
- 22 model call, tổng ≈ **18,805 token prompt/run**: planner-propose 397→865; reviewer-review 535→1142; synthesizer 781→1024; reviewer-semantic 930→959.
- Không tăng trưởng dây chuyền: sau lần nhảy r0→r1 (+105% review), mỗi vòng chỉ +10–40 token tổng (cơ chế `recent_full_rounds=1`, bundle.py:368–379 hoạt động đúng). Bloat chính là **baseline cố định mỗi role/call**.

**cProfile run mock (wall 0.904s, 22 model call):**

| Thành phần | cumtime | % wall |
|---|---|---|
| `sqlite.commit` ×76 | 0.526s | **58%** |
| `policies.apply_mutation` ×76 | 0.235s | 26% (validate lại toàn state mỗi commit) |
| `sqlite.load` ×280 | 0.166s | 18% |
| model calls ×22 | 0.011s | 1.3% |

Top tottime: `models.py:35 _utc` **12,529 calls**; `models.py:590 references` 377; `models.py:447 step_graph` 882 → hotspot là validation pydantic toàn-state, không phải node graph.

**SQL & state (1 run):** 913 statement (SELECT 597, INSERT 160, BEGIN 80, UPDATE 76) ≈ 41.5 stmt/model call; `events` 77 dòng, `operations` 76 (đọc lại sqlite.py:169 cho idempotency); `state_json` 1400B → **22,883B** (+~300B/rev, ×16.3 sau 5 vòng); commit 4–10ms mỗi lần.

**Song song hóa:** layout có fan-out `investigate → planner_analysis + reviewer_analysis` (graph.py:1603–1605). Probe delay 0.25s/call: phát hiện **đúng 1 cặp chồng lấn (cặp AnalysisOutput vòng 0)** → fan-out song song thật; mọi model call khác tuần tự (đúng ràng buộc pha). Wool không có response cache ở gateway; usage retry cộng dồn (trần ×3/call).

## 7. Đề xuất tối ưu (xếp theo mức tăng ÷ công sức; không patch)

| # | Đề xuất | Căn cứ số đo | Công sức |
|---|---|---|---|
| O1 | Giảm re-validation toàn-state mỗi commit (`apply_mutation` 26% wall; `_utc` 12.5k calls/run) — validate lọc theo phần thay đổi hoặc nạp state một lần mỗi node | cProfile mục 6 | trung-cao |
| O2 | Cắt `store.load` (280 lần/5 vòng) — cache state trong 1 node invocation, invalidate sau commit | cProfile mục 6; giữ đúng fencing | trung |
| O3 | Tỉa baseline prompt theo role (~0.9–1.15k token/call × 22 call/run) | bảng token mục 6 | thấp-trung |
| O4 | Bắt Follow-up A-1: thống nhất tập chặn giữa gate/validator/semantic-review + thêm test; giờ mutation chứng minh untested | M1 SURVIVED | thấp |
| O5 | Gộp INSERT events/operations (160 INSERTs) trong 1 transaction | SQL counts | trung |
| O6 | SSE interval cấu hình được + gộp query (8 stmt/2s/client) | bench SSE | thấp |

*Lưu ý:* % wall là của phần persistence (mock LLM≈0). Với LLM thật, O1–O2 hu.getProduct khi run dài/kích thước lớn; O3 dùng ngay (token = tiền).

## 8. KHÔNG KIỂM CHỨC ĐƯỢC

1. Accuracy usage settle với **provider thật** — cam kết không gọi LLM/API thật; chỉ đo trên adapter fake của repo (4 test providers bị skip vì thiếu key).
2. Tác động của độ lệch actual-vs-estimate cho call timeout thật (E-1) — cần provider thật.
3. Prompt bloat cho run kiểu **repo-based** (`repo=True`) — fixture đo là greenfield; aggregate kích thước repo thật chưa đo.
4. Hành vi live Docker sandbox — 6 test NOT_RUN (`ASTRA_P2_LIVE_SANDBOX=1`), ngoài đường production.
5. Kết quả song song hóa chỉ chứng minh với 1 cặp phân Adventures và mock delay; cơ chế executor/langgraph sâu hơn không kiểm chứng.
6. Mutation chỉ chạy full-suite một lần mỗi mutant; không đo flake-rate.

## 9. Xác nhận cuối

1. **Repo gốc không đổi ngoài `BACKEND_REVIEW.md` này** — `git status --porcelain=v1` (49 dòng) chụp TRƯỚC khi tạo file báo cáo có SHA256 `4683B5C68AB5E9BD519C8CCDD45DCF0C12EA6D49A589CC8AFEDDE518F7337CC4`, **byte-identical** với baseline chụp trước khi bắt đầu review (cùng hash). Sau khi tạo báo cáo, khác biệt duy nhất là dòng `?? BACKEND_REVIEW.md`.
2. **Bản sao thí nghiệm đã xóa**: `C:\Users\ADMIN\AppData\Local\Temp\opencode\astra_review\` (131 file copy backend + `evaluations/` + 5 backup mutation + harness scripts + JSON đo) xóa sạch sau khi ghi xong báo cáo; venv gốc chỉ tham chiếu đường dẫn tuyệt đối, không thay đổi.
3. Mutation đã **khôi phục đủ** trên bản sao trước khi xóa — SHA256 cả 5 file mutated khớp backup gốc: `59AB5F28…` (quality_validator.py), `3107B292…` (graph.py), `5574B33D…` (budget.py), `FEEFB253…` (finalization.py), `4AA717B9…` (verifier.py); run pytest sau khôi phục về đúng mức nền bản sao (549 passed + 2 fail môi trường copy: thiếu `frontend/` và dữ liệu historical run ở repo root — không phải lỗi mã).
4. Không sửa bất kỳ file nào trong `D:\Astra multi` ngoài file này.
