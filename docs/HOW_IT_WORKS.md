# Astra Multi — Mô hình hoạt động chi tiết (How It Works) — v2

> **Phiên bản 2.** Bản v1 bị phê là "chưa qua proofread, có lỗi, và có chỗ tự mâu thuẫn" — đúng.
> Bản này được viết lại: (a) soát lại toàn văn; (b) kiểm chứng từng luận điểm của bản phê bình bằng code, gắn
> tham chiếu `file:dòng`; (c) bổ sung chương ghi nhận **điểm yếu đã kiểm chứng** và **bảng đối chiếu
> phê bình ↔ kết quả kiểm chứng** (§1). Mọi chỗ tôi không tự kiểm lại được được ghi rõ ở §19.

- Phương pháp: đọc mã nguồn `backend/src/astra_multi/**`, `frontend/src/**`, `evaluations/*`, soi bằng grep
  cho từng luận điểm; các tham chiếu là kết quả tra cứu trực tiếp, không phải trích README.
- Trạng thái tài liệu: mô tả hệ thống **như nó đang chạy**, kể cả những phần chưa đấu nối (wired) hoặc
  là khung sườn (stub), thay vì mô tả ý định thiết kế.

---

## 1. Bảng đối chiếu: phê bình ↔ kết quả kiểm chứng

Mỗi hàng là một luận điểm trong phản biện; cột "Kết quả" là việc tôi tra lại code:

| # | Luận điểm | Kết quả | Bằng chứng |
|---|---|---|---|
| 0.1 | Tài liệu v1 đầy lỗi văn bản, chưa ai proofread | **Đúng — lỗi của tôi** | Đã sửa toàn bộ; danh mục lỗi v1 bên dưới §2 |
| 0.2 | "max output 2000" vs "max_tokens 16.000" tự mâu thuẫn | **Đúng — lỗi trình bày v1** | Ba số khác vai trò: 2000 = ước lượng budget (graph.py:157–184); 12000 = limit bundle orchestration (bundle.py:38–39); 16000 = `ContextLimits` nền cho lối gọi khác (bundle.py:70). v1 ghi lẫn lộn; v2 tách riêng §15 |
| 1.1 | Auth chỉ khớp prefix `/api/runs`; `/api/settings` không được bảo vệ? | **Đúng một phần, và lỗ hổng thật còn to hơn** | Middleware chỉ chặn `path.startswith("/api/runs")` (app.py:112). Mỗi endpoint settings **có** `Depends(require_admin)` (routes_auth_settings.py:394, 415, 434, 467, 482, 494, 568, 607, 655, 681) — nhưng `require_admin` **trả `None` thay vì raise khi chưa setup admin** (routes_auth_settings.py:316–318): trước khi setup, toàn bộ lưu/đọc provider, API key, role mapping **mở hoàn toàn** |
| 1.2 | `/auth/setup` ai gọi trước người đó làm chủ | **Đúng** | `setup_admin_password` chỉ kiểm tra hash chưa tồn tại (routes_auth_settings.py:356–361); không có cơ chế chặn (chẳng hạn bind-token in ra console, hoặc chỉ lắng nghe loopback) |
| 1.3 | Token tự chế HMAC 2 phần; không revoke; PBKDF2 100k dưới chuẩn | **Đúng** | crypto.py:88–109 — stateless 2-part; `jti` sinh ra nhưng không bao giờ được đối chiếu vào đâu → không revoke được; hạn 7 ngày. PBKDF2-HMAC-SHA256 100.000 vòng (crypto.py:34) so khuyến nghị OWASP 2023 ~600.000 cho SHA-256 |
| 1.4 | Không rate-limit login; đổi mật khẩu không vô hiệu token cũ | **Đúng** | `login_admin` không có limiter (routes_auth_settings.py:371–389); `change_password` chỉ đổi hash/salt, **không rotate `auth_secret_key`** (routes_auth_settings.py:404–407) → token cũ còn hạn vẫn hợp lệ |
| 1.5 | Token `?token=` lọt URL/log/history/referer | **Đúng** | api.ts:450–452 gắn token vào query cho EventSource; middleware chấp nhận query token (app.py:120–128). EventSource không set header được là thật; cookie httpOnly hoặc fetch-stream là phương án thay thế — hiện chưa có |
| 1.6 | SSRF qua `/settings/providers/test` (base_url tự nhập, cho phép loopback HTTP) | **Đúng** | Hợp đồng profile cho phép HTTP cho `localhost/127.0.0.1/[::1]` (provider_config.py:50–55); endpoint test gọi thẳng `{base_url}/chat/completions` hoặc `{...}:generateContent` (routes_auth_settings.py:537–540). Sau setup: yêu cầu admin; trước setup: mở (mục 1.1) |
| 1.7 | "Tương tự DocumentFetcher" (SSRF) | **Không chính xác một phần** | documents.py:19 và 44–48: `allow_loopback_http=False` mặc định, bắt buộc HTTPS ngoài loopback, còn kiểm tra URL nằm trong scope prefix. Bề mặt còn lại: HTTPS tới host bất kỳ trong scope — không phải mở rộng loopback như endpoint test |
| 1.8 | `snapshot_path` đọc thư mục tuỳ ý rồi gửi cho LLM; không secret scanning | **Không chính xác (hiện tại)** — phần secret scanning đúng | `snapshot_path` chỉ tồn tại trong schema (api/schemas.py:28) và **không có mã nào tiêu thụ** (grep toàn src chỉ 1 kết quả). Chưa có đường chạy thật nào đọc thư mục tùy ý từ API. Không có secret scanning là đúng: `SelectionPolicy` lọc theo *tên* file (`.env*`, `*.pem`…) (snapshots.py:20), nội dung key hard-code trong config.js sẽ lọt qua |
| 1.9 | Fernet master key nằm cạnh DB → mã hoá là phim trường | **Đúng** | Master key lưu trong chính bảng `app_settings` của SQLite (crypto.py:45–52); ai đọc được DB thì đọc được key và mọi API key |
| 1.10 | Xoá run không xoá artifacts, không có GC | **Đúng** | `delete()` giữ nguyên content-addressed artifacts theo thiết kế ("intentionally kept", sqlite.py:350–358); chỉ xoá `errors/{run}.log` + `semantic_reviews/{run}.json`; không có GC |
| 1.11 | xKiro (gateway thứ ba) là provider mặc định active | **Đúng** | Seed khi DB trống: `xkiro` active (routes_auth_settings.py:292–305). Toán của ToS/log/retention của bên thứ ba nằm ngoài code — nhưng đây là mặc định gửi dữ liệu đi, và nên đổi |
| 2.1 | **Cancel không cancel được**: `graph.invoke` chạy trong executor thread; cancel asyncio task + timeout 5s không giết thread; tiếp tục đốt tiền khi UI đã báo CANCELLED | **Đúng** | worker.py:58–76 chỉ cancel task *chờ* graph; graph chạy ở `run_in_executor(None, app.invoke…)` (worker.py:215) — thread executor không thể bị ngắt; mọi LLM call đang dở vẫn chạy tới xong. Chỉ các commit *sau đó* mới đụng LeaseLost (lease đã bị release) |
| 2.2 | Restart server → run kẹt RUNNING tới lease hết hạn; chỉ resume thủ công | **Đúng** | `lifespan` chỉ làm shutdown (app.py:87–96); không có recovery khi khởi động; `/resume` là API thủ công |
| 2.3 | Connection SQLite dùng chung `check_same_thread=False`; SSE poll 0.5s/client + `json_extract` trên blob to → chi phí/CPU tăng theo số client | **Đúng, với điều chỉnh cơ chế** | Một connection duy nhất (sqlite.py:63–67); `events()` đọc **không qua `_tx_lock`** (sqlite.py:174–179) → nhiều thread cùng dùng một connection sqlite3 là hành vi không định nghĩa (đua, không nhất thiết "database is locked" vì WAL + 1 process). `get_run_status_info` dùng `json_extract` trên `state_json` (sqlite.py:155–157); loop SSE poll mỗi 0.5s cho mỗi client |
| 2.4 | "Event-sourcing" không replay được; state là blob ghi đè cả cục | **Đúng** | Commit pipeline: ghi đè toàn bộ `state_json` + event kèm theo (sqlite.py:189–268); bảng `operations` dùng cho idempotency, không có replayer |
| 2.5 | Retry khi ContextOverflow "giữ nửa cuối messages" → cắt đúng system prompt + schema | **Đúng** | model_gateway.py:435: `messages = messages[-len(messages)//2:]` — nửa đầu bị bỏ, system prompt/schema thường nằm ở đầu |
| 2.6 | Backoff `1s×attempt`, không jitter, không Retry-After; marker `<!-- attempt n -->` nhét vào prompt | **Đúng** | model_gateway.py:379, 419, 449 — `time.sleep(1 * attempt)`; comment nguyên văn ghi "Exponential backoff" cho backoff tuyến tính; không đọc `Retry-After`; marker ở 218–223 |
| 2.7 | Output mặc định 2000 token làm Synthesizer bị cắt cụt → JSON hỏng → PARTIAL khó debug | **Cơ chế sai** — phần "lỗi infra bọc thành PARTIAL" đúng | 2000 (graph.py:180) chỉ là số liệu **ước lượng** cho budget reservation (graph.py:165, 200); **không truyền vào API thật**: OpenAI `omit` max_tokens khi `limits.max_tokens is None` (providers.py:190–192), Google nhận `max_output_tokens=None` (providers.py:233) → không có cap 2000 trên output thật. Phần đúng: lỗi schema/infra thật sự bị thể hiện thành `PARTIAL` với stop_reason "Model output failed schema validation…" thay vì một trạng thái FAILED chuyên biệt |
| 2.8 | Ước lượng `len//4` và $0.01/1k cho mọi model là "số bịa" | **Đúng** | model_gateway.py:167–168 — đếm **ký tự** (`len(str)`), không phải byte; tiếng Việt mỗi ký tự ≈ 1 token → underestimate ~4×; gpt-4o-mini giá thật thấp hơn fallback ~2 bậc → cost overestimate lớn. Đây là heuristic bảo vệ trần, không phải đo lường |
| 2.9 | Bundle 12.000 bytes là "cái tăm" cho repo thật; mức degrade cuối chỉ còn `{id, step_count, truncated:true}` + 5 issue `{id, severity}` | **Đúng** | bundle.py:38–39 (`DEFAULT_ORCHESTRATION_MAX_TOKENS = 12000`, env `ASTRA_MULTI_MAX_CONTEXT_BYTES`); 4 mức degrade kết thúc ở mức 3 như mô tả. Với repo thật + plan nhiều step + issues, reviewer "chấm" trên mô tả rút gọn là kịch bản thật |
| 2.10 | Issue ID "deterministic" = sha256(run:round:claim); claim diễn đạt khác → ID mới; "alias map" là vá trên vá | **Đúng** | `ISSUE-{sha256(run_id:round:claim)[:8]}`; review_node phải dựng `res_alias_map` gồm cả `ISSUE-1`, `#1`, số thứ tự (graph.py:788–807) — tức chính hệ thống thừa nhận ID referential không ổn định giữa các vòng |
| 2.11 | StagnationDetector window=2 + max_rounds=2 → dead code | **Đúng có điều chỉnh** | `record_round` gọi ở semantic_review mỗi vòng (graph.py:1406); `is_stagnant` cần ≥2 mẫu (termination.py:64–70). Với max_rounds=2: gate vòng 1 chỉ có 1 mẫu → không thể stagnant; gate vòng 2 đủ 2 mẫu nhưng `round_num >= max_rounds` đã export sẵn → **stagnation không thay đổi quyết định vòng lặp nào**, chỉ thêm chữ vào `stop_reason`. Chỉ khi max_rounds≥3 nó mới tham gia điều khiển (graph.py:1567–1574) |
| 2.12 | `recursion_limit 150` với 2 vòng là vô dụng | **Đúng** | Guard chống vòng vô hạn vô tình thành hằng số không bao giờ chạm với graph hiện tại (2 vòng × ~13 node) |
| 3.1 | Static grounding = regex + cửa sổ negation 70 ký tự; tiếng Việt phủ định đa dạng; 2 chiều FP/FN | **Đúng** | technical_grounding.py: `is_negated_or_prohibition` cửa sổ 70 ký tự; `TECH-FILE-PROTOCOL` bằng 3 regex, MOCKAPI bằng substring… Recall/precision bị giới hạn bởi cách tiếp cận |
| 3.2 | Sandbox chỉ là "sinh script grep rồi chạy lại chính nó"; Docker flags là security theatre; không chạy code plan | **Đúng — và mạnh hơn phê bình** | verify_node gọi `PlanSandboxVerifier.verify()` → `execute_verification()` chạy `subprocess.run([sys.executable, script])` trên **HOST python** (verifier.py:314–339). **DockerRunner/WindowsRunner chưa được đấu nối vào workflow** — script tự sinh thì chạy, các runner hardened chỉ chạy trong demo/tests. v1 sai khi ghi VERIFY dùng Docker/Windows runner |
| 3.3 | WindowsRunner chỉ tempdir + env tối thiểu + taskkill; không giới hạn tài nguyên/mạng | **Đúng** | sandbox/runner.py: WindowsRunner probe chỉ check `os.name=="nt"` + python; execute = tempdir, env tối thiểu (`PATH`, `PATHEXT`, `PYTHONUNBUFFERED`), timeout → `taskkill /F /T /PID`. Không cgroup/rlimit/job-object, không cô lập mạng |
| 3.4 | TechStackTruthTable 4 ràng buộc hardcode = overfitting vào nội bộ bài tập | **Đúng** | 4 entry cố định: `TECH-FILE-PROTOCOL / TECH-MOCKAPI / TECH-REALTIME-CHAT / TECH-NO-BUILD` (models.py:107–117 + technical_grounding.py). Với đề khác 4 góc này, "technical grounding" gần như trống |
| 3.5 | "Mọi claim phải có evidence" nhưng CLAIM-TRUTH tự phát; không ai kiểm claim có hỗ trợ đề xuất không; greenfield không snapshot → vòng tròn khép kín | **Đúng — và mạnh hơn** | `snapshot_node` là **stub** — không capture gì (graph.py:467–469: chỉ transition + log "[SNAPSHOT] Snapshot verified"). `SnapshotStore.capture` chỉ được gọi ở demo/tests (grep `.capture(` toàn src: 1 nơi ngoài tests). Planner chỉ lọc `claim_ids` theo tồn tại (graph.py:628: `filtered_claims = [cid … if cid in valid_claims]`) — không kiểm chứng nội dung claim. ToolBroker yêu cầu snapshot → thực tế không dùng được trong run thật |
| 4.1 | RULE-FULFILL-001 = độ dài ≥15 + blacklist → Goodhart | **Đúng** | quality_validator.py: `concrete_deliverable ≥ 15 ký tự`, cấm placeholder ("tbd","n/a","todo","chưa có","sẽ bổ sung","phủ requirement"…) — câu "Triển khai chức năng theo yêu cầu đã nêu" qua được |
| 4.2 | Luật DAG tuỳ tiện (≤2 root; depth ≥2; INTEGRATION cần SETUP ancestor; cấm isolated) → Synthesizer bịa dependency | **Đúng (rủi ro thật)** | RULE-DAG-001…008 trong quality_validator.py. Không phủ nhận luật có tính hợp lý riêng; nhưng chúng áp đặt nặng, dễ dẫn tới DAG "đẹp luật" thay vì đúng thực tế |
| 4.3 | Rubric do LLM sinh, chấm bởi LLM cùng họ → lỗi tương quan | **Không chính xác một phần** | Rubric sinh bằng **code deterministic** từ acceptance criteria (contract_extractor.py:388–419), không phải LLM. Phần vẫn đúng: acceptance mặc định là câu tự sinh; SEMANTIC_REVIEW do Reviewer LLM chấm; nếu Planner & Reviewer cùng model thì "phản biện độc lập" còn tương quan lỗi — UI chỉ **cảnh báo**, không cấm |
| 4.4 | Isolation chỉ tồn tại round 1; từ PROPOSE hai bên thấy nhau; round 2 không chạy lại phân tích độc lập | **Đúng** | Context bundle chỉ loại plan/proposal/issues khi `phase == INDEPENDENT_ANALYSIS` (bundle.py:435–466); đồ thị `gate → propose` trực tiếp (graph.py:1613–1620), không quay lại independent_analysis |
| 4.5 | Hạ tầng nặng (lease/epoch/idempotency/content-addressed/WAL FULL) cho công cụ single-node, phần quyết định chất lượng mỏng | **Đúng (đánh giá tư duy)** | Trái nghịch có thật: nơi quyết định chất lượng là prompt/rubric/grounding — mà các cơ chế đó (§6.4, §13) là regex/truth-table hardcode trong khi persistence cực kỳ công phu |
| 5.1 | Evaluations là test pipeline (fake adapter, seed cố định), không phải thí nghiệm chất lượng; ngân sách khác nhau (15k vs 10k) | **Đúng** | multi_agent_runner.py:19 (`budget_cap_tokens=15000`, token dùng = `min(cap, 4500 + req·680)` — không gọi LLM); baseline_runner.py:20 (10000, công thức khác); không có benchmark sống vs single-shot cùng ngân sách trong repo |
| 5.2 | transition_run phát đôi thành transition_phase vô lý; vừa SSE vừa polling dư thừa | **Đúng** | app.py:453 phát đôi ngay trong luồng sinh SSE (không có "client cũ" nào trước đó — backend & frontend cùng repo); App.tsx:486/503 vừa SSE vừa polling 2–2.5s an toàn |

**Tổng:** mọi luận điểm trong bảng (37 hàng, §1) đều đã được đối chiếu với code; 4 hàng được kết luận
"cơ chế sai hoặc sai mức độ" (1.7, 1.8, 2.7, 4.3) — đều có bằng chứng ngược bằng code cụ thể; 2 hàng
(3.2, 3.5) thực tế còn nghiêm trọng hơn bản phê bình.

---

## 2. Lỗi văn bản của v1 (được nêu và đã sửa)

| Lỗi v1 | Loại | Sửa trong v2 |
|---|---|---|
| "Èm investigate→planner_analysis" | ký tự hỏng | "edge `investigate → planner_analysis`" (§6.4) |
| "Duyện lệ `available`" | ký tự hỏng | "nguyên tắc: ai giữ lease mới nhất thì được quyền ghi" (§11) |
| "cửa hình-thanh và vòng lặp" | ký tự hỏng | "cổng kiểm tra chất lượng và vòng lặp" (§6.4, node gate) |
| "(ver contenido hash)" | trộn ngôn ngữ | "kiểm chứng content hash" (§11) |
| "đại ai không khớp schema" | dư ký tự | "nếu output không khớp schema" (§10) |
| "xi phạm" | chính tả | "vi phạm" |
| "`ISSUE-SANDBOX-*. Ví dụ blocking issue` buộc Synthesizer" | câu dán nhầm | viết lại nguyên câu (§6.4, node VERIFY); kèm phát hiện mạnh hơn: VERIFY không dùng Docker/Windows runner như v1 mô tả — xem bảng §1 hàng 3.2 |
| Bảng hằng số ghi "Max output tokens mặc định 2000" như giới hạn gọi thật | sai ngữ nghĩa | tách 3 con số đúng vai trò (§15) |

Lỗi ngữ nghĩa lớn nhất của v1 (được phê chính xác): mô tả VERIFY chạy "DockerRunner hoặc WindowsRunner" — thực tế graph chạy `PlanSandboxVerifier` trên **host python subprocess**; cả hai runner hardened **chưa được đấu nối** vào workflow. Cfr §9.

---

## 3. Hệ thống này làm gì (tóm tắt không marketing)

**Astra Multi** là hệ thống đa tác nhân (FastAPI + LangGraph + SQLite + React) làm **thiết kế kiến trúc phần
mềm từ yêu cầu đầu vào**, đầu ra mục tiêu là kế hoạch triển khai Markdown/JSON kèm decision log, issue log,
evidence index. Giá trị thực tế của hệ thống — đặc biệt "tốt hơn một lần hỏi thẳng model mạnh" — **chưa có
benchmark sống nào trong repo chứng minh** (xem §16). Mọi so sánh trong README là tuyên bố, không phải kết
quả đo.

---

## 4. Bản đồ kiến trúc (đã hiệu chỉnh theo code thật)

```text
┌────────────────────────────────────────────────────────────────────────────┐
│        FRONTEND (React 18 + TS + Vite): port 5173 dev (proxy /api)          │
│        prod: FastAPI mount frontend/dist tại / (một process duy nhất)       │
│  7 tab · PhaseTracker 11 phase · SSE + polling an toàn 2/2.5/12s + 2.5/6/15s│
└──────────────▲───────────────────────────────────────────────▲─────────────┘
               │ REST + SSE (Bearer header hoặc ?token= cho SSE)
┌──────────────┴───────────────────────────────────────────────┴─────────────┐
│           BACKEND API  FastAPI + Uvicorn  (127.0.0.1:8000)                  │
│  /api/runs*   ← auth middleware (Bearer hoặc ?token=)                       │
│  /api/auth/* · /api/settings/* ← auth **theo từng route** (require_admin)   │
│   ⚠ trước khi setup admin: require_admin trả None → settings mở hoàn toàn   │
└──────────────┬─────────────────────────────────────────────────────────────┘
               │ RunWorker.start_run → asyncio.Task; graph.invoke trong
               │   executor thread (không thể bị ngắt khi cancel)
┌──────────────┴─────────────────────────────────────────────────────────────┐
│  LANGGRAPH 13 node — intake → intake_gate ⇄ → snapshot(STUB!) → investigate │
│      ├→ planner_analysis ─┐                                                │
│      └→ reviewer_analysis ┴→ propose → review → verify → revise           │
│           → semantic_review → gate ⇄ loop → export → END                   │
│  Ghi/đọc qua WorkflowController → SQLiteStore.commit (lease + idempotent)   │
│  ⚠ các bộ "chưa đấu nối": SnapshotStore.capture, DockerRunner/WindowsRunner,│
│    ToolBroker (cần snapshot), snapshot_path (field chết trong schema)      │
└──────┬───────────────────┬──────────────────────┬──────────────────────────┘
       │                   │                      │
┌──────┴─────────┐  ┌──────┴─────────┐  ┌──────────┴───────────────────────────┐
│ ModelGateway    │  │ SQLite WAL     │  │ Sandbox thật đang chạy:               │
│ openai SDK │    │  │ runs/events/   │  │  PlanSandboxVerifier → subprocess     │
│ google genai │  │  │ operations/    │  │  [sys.executable, verify_script]      │
│ openai-compat→ │  │ leases/        │  │  trên HOST python (không Docker)      │
│  xKiro/Router   │  │ app_settings/  │  │  Docker/Windows runners: DEMO/TEST    │
│ retry tuyến tính│  │ provider_cfgs  │  │  tool ToolBroker: DEMO/TEST           │
│ + output repair │  │ + artifacts/   │  │                                       │
└──────┬─────────┘  │ (sha256 dedup)│  └──────────────────────────────────────┘
             │        └──────┬────────┘
        LLM API        .local/domain.sqlite + .local/artifacts/*
```

**Nguyên tắc ranh giới:**

- Backend ↔ frontend chỉ qua HTTP/SSE.
- Graph không ghi DB trực tiếp: mọi thay đổi qua `WorkflowController` → `SQLiteStore.commit` (một SQLite
  connection duy nhất, `_tx_lock` cho ghi; đọc **không** qua lock — xem §11 về rủi ro).
- Gateway không quyết định luồng; node gọi `gateway.call(role, schema, messages)` nhận kết quả đã validate
  theo schema Pydantic; lỗi schema không sửa được → `SchemaError("REPAIR_FAILED")`.

---

## 5. Shared Blackboard — cơ chế hợp tác

Trạng thái chuẩn tắc là **một** `RunState` (Pydantic) nằm trong SQLite; tác nhân không trò chuyện trực
tiếp — chúng xen kẽ đọc một bundle và ghi lệnh:

```text
Tác nhân ─đọc─► ContextBuilder.build_context(state, role, phase) ─► ContextBundle (JSON prompt)
Tác nhân ─ghi──► WorkflowController.<method>(...) ─► Command ─► SQLiteStore.commit(lease)
```

Chỉ tồn tại đúng **6 loại mutation** (`domain/commands.py`):

| Command | Việc |
|---|---|
| `CommitPlan` | commit một `PlanRevision` mới |
| `AddRecord` | thêm `Claim/Evidence/Proposal/Issue/Decision/ToolCall/ModelCall/Question/ValidationResult/BudgetReservation` |
| `TransitionRun` | đổi `phase` (11 phase) / `status` (6 trạng thái) |
| `ChangeIssue` | `open → investigating → proposed_resolution → resolved / rejected / duplicate` |
| `AnswerQuestion` | trả lời câu hỏi Human-in-the-Loop |
| `ReviseTask` | sửa `TaskSpec` giữa chừng |

Mỗi command mang `expected_revision` (khóa lạc quan), `node`, `logical_operation_id` (idempotency), `actor`.

**Vai trò (agents/roles.py, orchestration/roles.py):**

| Tác nhân | Nhiệm vụ | Phase | Đầu ra |
|---|---|---|---|
| Planner | khởi xướng & duy trì giải pháp | INDEPENDENT_ANALYSIS, PROPOSE | `AnalysisOutput`, `ProposalOutput` |
| Reviewer | phản biện độc lập, chấm rubric | INDEPENDENT_ANALYSIS, REVIEW, SEMANTIC_REVIEW | `ReviewOutput` (issues), semantic assessment |
| Synthesizer | dung hòa thành kế hoạch | REVISE | `SynthesizerOutput` → `PlanRevision` |
| Verifier | **không phải LLM** | VERIFY | grounding regex + sandbox-verifier script |
| P4 service | không phải LLM | QUALITY_GATE / finalize | validator, 5-pillar gate |

---

## 6. Vòng đời một Run

### 6.1. Trạng thái và phase

- `RunPhase` (11 phase, domain/models.py:60–71): `INTAKE → SNAPSHOT → INVESTIGATE → INDEPENDENT_ANALYSIS
  → PROPOSE → REVIEW → VERIFY → REVISE → SEMANTIC_REVIEW → QUALITY_GATE → EXPORT`.
- `RunStatus`: `RUNNING / WAITING_FOR_INPUT / FINAL / PARTIAL / FAILED / CANCELLED` (models.py:74–85).
  `FINAL` **chỉ** đạt được bởi P4 service qua `/finalize` (graph.py:1557–1559).

### 6.2. Tạo Run

`POST /api/runs` (idempotency-key) hoặc CLI `create`:
1. `classify_all()` phân loại từng requirement (`req_type`, `expected_artifact_type`, tiêu chí chấp nhận
   mặc định tự sinh: "Plan nêu cơ chế cụ thể đáp ứng yêu cầu này và cách kiểm chứng: {text}").
2. `SQLiteStore.create` ghi `runs` + event `run_created`.
3. Ghim **snapshot cấu hình vai trò bất biến** (`run_role_mappings:{run_id}` + artifact metadata) — không
   đổi model giữa chừng cho một run.
4. `worker.start_run(run_id, max_rounds)` → asyncio task.
5. Nếu có `parent_run_id` (clone) → run cha phải terminal.

### 6.3. RunWorker

- Lease `worker-{run_id}`, TTL 300s; heartbeat mỗi 30s; release ở `finally`.
- `BudgetService` khi request có `token_limit / cost_limit / call_limit` (reservation atomic, tính cả
  chi phí retry/repair); chi tiết budget: xem §15.
- Giải mã role-mapping snapshot + API key riêng theo vai (Fernet).
- `graph.invoke(...)` chạy trong **executor thread** (`run_in_executor`, worker.py:215); trong lúc chạy
  thêm heartbeat để giữ lease. Lỗi: schema validation → `PARTIAL`; khác → `FAILED`; traceback vào
  `artifacts/errors/{run_id}.log`. Cancel: `stop_task` chỉ cancel task chờ — thread graph **không dừng**
  (điểm yếu đã kiểm chứng §1, mục 2.1).
- Restart server: không có recovery lúc startup — run kẹt RUNNING tới lease hết hạn (300s), cần `/resume`
  thủ công (điểm 2.2 §1).

### 6.4. Đi qua các node (theo code thật)

#### INTAKE + intake_gate
- Chuẩn hoá task; `detect_deliverable_gaps` tìm noun "deliverable" thiếu → tự bù REQ-DELIV/REQ-ORG; tối đa
  `max_intake_retries = 2` vòng; conditional edge `intake_gate → intake | snapshot`.
- Sinh **RubricChecklist bằng code deterministic** từ acceptance criteria (contract_extractor.py:388–419).
  Chú ý: với requirement không có acceptance, criterion mặc định là chính câu requirement — chất lượng
  rubric chỉ dõi theo chất lượng input.

#### SNAPSHOT — **stub**
- `snapshot_node` nguyên văn (graph.py:467–469):
  ```python
  def snapshot_node(state):
      ctrl.transition_phase(RunPhase.INVESTIGATE)
      return {"events": ["[SNAPSHOT] Snapshot verified"]}
  ```
  **Không có capture nào xảy ra trong workflow.** Mọi mô tả về SnapshotStore (double-scan, quota, chặn
  symlink, 10k files/4MiB/64MiB) là nội dung thư viện — chỉ được chạy ở demo/tests. Hệ quả: toàn bộ chuỗi
  "bằng chứng gắn snapshot" là **khung sườn chưa đấu nối** (xem 3.5 §1).

#### INVESTIGATE
- Dựng **TechStackTruthTable = 4 entry hardcode** (`TECH-FILE-PROTOCOL / TECH-MOCKAPI / TECH-REALTIME-CHAT
  / TECH-NO-BUILD`), mỗi entry gồm `physical_limitation, mandated_pattern, prohibited_patterns`; ghi
  `Claim(kind="fact")` dạng `CLAIM-TRUTH-*` — claim tự phát, không evidence bên ngoài (3.5 §1).
- Goal/requirement không chạm 4 góc này → truth table rỗng → grounding bỏ trống.

#### INDEPENDENT_ANALYSIS (fan-out)
- Edge: `investigate → planner_analysis` và `investigate → reviewer_analysis`, hội về `propose`
  (graph.py:1604–1607).
- Bundle **loại** `plan/proposal/open_issues/decisions` ở đúng phase này (bundle.py:435+) → Planner và
  Reviewer phân tích độc lập chỉ từ task + repo_map + evidence. **Isolation chỉ tồn tại ở đây**: từ PROPOSE
  trở đi bundle có cả proposal/plan/issues; vòng 2 không quay lại independent_analysis (4.4 §1).

#### PROPOSE
- Planner call model với schema `ProposalOutput`: approach/alternatives/tradeoffs/coverage/decisions/
  design_artifacts (mỗi design artifact trỏ ≥1 requirement)/`claim_ids` — chỉ lọc theo `claim_ids ∈
  valid_claims` (graph.py:628), **không kiểm chứng nội dung claim có hỗ trợ đề xuất hay không**.

#### REVIEW
- Reviewer 3 lớp audit trên proposal: rubric / constraint / out-of-scope → issues
  (`claim, impact, verification_request, suggested_resolution, severity blocking|warning|info|nitpick,
  requirement_ids`).
- ID issue = `ISSUE-{sha256(run:round:claim)[:8]}` — deterministic **trong một vòng**; claim sinh lại khác
  chữ ở vòng sau → ID mới; review_node phải map "ISSUE-1 / #1 / số thứ tự" về issue thật qua
  `res_alias_map` (graph.py:788–807) — chính cơ chế vá này thừa nhận điểm gãy (2.10 §1).
- Resolutions áp qua `ChangeIssue`.

#### VERIFY — hai "tầng kiểm chứng", không LLM
1. **Static grounding**: `verify_technical_grounding` quét regex `prohibited_patterns` trên proposal+plan;
   negation-window 70 ký tự (`không/cấm/tránh/instead of…`) chống false-positive; mỗi vi phạm → `Issue
   ISSUE-TECH-*` severity blocking (graph.py:834–887). Nhận định: FP và FN là giới hạn tự nhiên của phương
   pháp điều tra ngôn ngữ tự nhiên bằng regex — không thể đảm bảo đúng/sai (3.1 §1).
2. **Sandbox verifier — script tự sinh chạy trên host**:
   `PlanSandboxVerifier.verify()` (verifier.py:507) sinh `verify_constraints.py` (print
   `[CONSTRAINT_VIOLATION]`, `sys.exit(1)` khi sai) rồi `execute_verification` chạy
   `subprocess.run([sys.executable, script], timeout=15, CREATE_NO_WINDOW on Windows)` (verifier.py:314–339).
  FAIL → `ValidationResult` + `Issue ISSUE-SANDBOX-*` blocking. **Không có code/hành động của plan nào được
   thực thi**; Docker/Windows runner (cùng hằng số hardened như `--network none --cap-drop=ALL`) chỉ dùng ở
   demo/tests (3.2 §1, 3.3 §1). Windows: chạy ngay trên host với quyền host.

#### REVISE
- `SynthesizerOutput → PlanRevision`: steps-DAG (`phase_type`, deliverables, completion_criteria,
  `dependency_ids`, `requirement_ids`, `requirement_fulfillments` với `concrete_deliverable`/
  `verification_method`), decisions, design_artifacts, `issues_addressed` (qua `res_alias_map`).
- Commit qua `CommitPlan` → revision +1.

#### SEMANTIC_REVIEW
- Reviewer LLM chấm từng RubricItem → MET/PARTIAL/MISSING; merge verdicts: rubric-deterministic + model +
  "Unverified-FAIL khi thiếu"; lập `SemanticReviewAssessment{passed, reviewed_plan_revision, …}` persist
  tại `app_settings["semantic_review:{run_id}"]` + `artifacts/semantic_reviews/{run_id}.json`.
- `StagnationDetector.record_round` mỗi vòng (graph.py:1406).

#### QUALITY_GATE (gate)
- Problems gom: plan chưa commit; blocking chưa resolved; warning còn mở; semantic chưa pass; **coverage
  thiếu** (req chưa được step/design_artifact nào trỏ); stagnation flag; toàn bộ BLOCKER từ
  `StructuralQualityValidator` (§13).
- Conditional edge `should_loop_or_export` (graph.py:1567–1574):
  `gate_passed → export`; ngược lại nếu `round < max_rounds` và **không stagnant** → `propose` (vòng tiếp);
  còn lại → export. **Với max_rounds mặc định = 2, stagnation không bao giờ thay đổi quyết định này**
  (2.11 §1).

#### EXPORT
- `transition_phase(EXPORT)`, sau đó status terminal: gate pass → `FINAL` nếu actor là
  `P4-quality-service` (đường finalize), ngược lại → `PARTIAL` với reason "MVP candidate generated
  (awaiting P4 quality certification)"; gate fail → `PARTIAL` với stop_reason (graph.py:1549–1565).
  Artifacts không ghi file cứng — export on-demand (`GET /export?format=`),
  `PlanExporter.export_json/export_markdown`.

### 6.5. PARTIAL → FINAL: 5-Pillar Finalization Gate

`POST /finalize` (lease `quality-service`, TTL 30s) → `FinalizationService.evaluate(state, semantic_review)`:

| Pillar | Kiểm tra chính |
|---|---|
| 1 Structural | không BLOCKER: `RULE-STRUCT-001`, `RULE-UNIQUE-001`, `RULE-DAG-001…008` + plan có steps |
| 2 Contract & Deliverable | coverage 100%, refs hợp lệ, step có deliverables/criteria, fulfillments không placeholder |
| 3 Rubric Audit | semantic review tồn tại, `reviewed_plan_revision` == plan hiện hành (không "stale"), passed, 100% rubric MET |
| 4 Grounding & Anti-pattern | 0 vi phạm truth-table trên plan, 0 sandbox FAIL chưa được bù |
| 5 Issue Resolution | không blocking mở; không warning còn OPEN/INVESTIGATING/PROPOSED |

Với `Question.blocking` chưa trả lời → `WAITING_FOR_INPUT` (answer qua `/answers`, rồi `/resume`); còn
ngược lại cả 5 pass → `PARTIAL → FINAL`. Đây là transition terminal duy nhất vào `FINAL`.

---

## 7. Cơ chế vòng lặp & các đường kết thúc

- `max_rounds` mặc định 2 (`1..10` khi tạo). Với giá trị 2: round-1 gate thất bại → loop; round-2 gate
  thất bại → export (PARTIAL với stop_reason "max_rounds_reached: …"). Cơ chế loop chỉ có tác dụng hội tụ
  **khi max_rounds ≥ 3** + stagnation có mẫu ≥ 2.
- Cancel (UI/CLI): `stop_task` cancel asyncio task (timeout 5s) + transition CANCELLED; sau đó release
  lease. Nếu worker còn dở call LLM → call đó vẫn burn ngân sách (2.1 §1), commit sau sẽ bị LeaseLost do
  lease đã release.
- Budget: `BudgetService` + `BudgetHook` có thể giết call khi vượt trần → run kết thúc.
- `recursion_limit 150` cứng (compile + worker invoke config) — không bao giờ chạm với cấu trúc hiện tại.

---

## 8. Phân vai model & API key theo vai

- Mỗi run ghim mapping `planner / reviewer / synthesizer → (provider, model, has_custom_api_key)`.
- Role-specific key mã hoá Fernet (`api_key_enc`); giải mã lúc chạy; thứ tự key:
  role override → env var provider → OS keyring.
- UI hiện tại: nếu Planner & Synthesizer chia sẻ một model — **chỉ cảnh báo**, không cấm (4.3 §1).
- Seed mặc định khi DB trống: `xkiro` active (openai-compatible `https://api.xkiro.com/v1`),
  `openai`, `google` (hệ quả dữ liệu bên thứ ba xem §12).
- Quét model: OpenAI-compatible GET `{base}/models`; Google ListModels + lọc `generateContent`; sort `:free`
  trước.

---

## 9. Context engineering — bundle của mỗi tác nhân

- Limit chính: **12.000 bytes** cho bundle orchestration (bundle.py:38–39; env `ASTRA_MULTI_MAX_CONTEXT_BYTES`);
  `ContextLimits` nền 16.000 cho lối gọi khác (bundle.py:70). Tokenizer = `len(text.encode("utf-8"))`.
- Baseline: `task` (goal, requirements đầy đủ req_type/expected_artifact_type/acceptance), `snapshot`
  (nếu có — hiện workflow không tạo), `repo_map` ≤ 64 path, `essential_sources`; **từ PROPOSE trở đi** mới
  thêm `plan / proposal (id+approach+coverage) / open_issues (blocking trước) / closed_resolutions /
  recent_model_calls (+prior summary) / recent_events (+milestones)`.
- **4 mức degrade** khi vượt limit: cắt repo_map → tóm tắt plan/issue (200 ký tự) → minimal (100 ký tự,
  giảm cap số issue dần) → mức 3: bỏ hẳn thân bài, chỉ còn `plan: {id, step_count, truncated: true}` +
  tối đa 5 issue `{id, severity}`; sau đó ghi note "baseline_notes". Vượt tất cả → `ContextOverflow`.
- Evidence render dạng "UNTRUSTED EVIDENCE {id} [{locator}] hash=… status=…"; evidence không khớp snapshot
  hiện hành bị loại ("stale evidence cannot enter current context") — kiểm tra này chỉ có ý nghĩa khi đã
  có snapshot; hiện trường không có (§6.4).
- Điểm cần nhớ: **bundle là nguồn hiển thị duy nhất cho reviewer chấm plan** — ở mức degrade cao, reviewer
  chấm một kế hoạch mà nó gần như không nhìn thấy (2.9 §1).

---

## 10. Model Gateway & Providers

- Routing: `ProviderProfile{kind: openai|google|openai-compatible, base_url, model, json_mode}`.
  OpenAI-compatible dùng cùng adapter `_generate_openai` với base_url riêng (xKiro/OpenRouter); Google dùng
  `google.genai`. Hợp đồng base_url: HTTPS bắt buộc trừ loopback (provider_config.py:50–55) — chính là
  bề mặt SSRF đã ghi ở §1.6.
- Retry (mặc định `max_retries=2`, timeout 120s):
  - RateLimit/Timeout/ProviderError → lại với `time.sleep(1 * attempt)` — **tuyến tính**, không jitter,
    không đọc `Retry-After`; comment trong code ghi "Exponential backoff" nhưng không đúng (model_gateway.py:379).
  - AuthError / BadRequestError → không retry.
  - `ContextOverflowError` → retry với `messages[-len(messages)//2:]` — cắt nửa đầu (system + schema) (2.5 §1).
  - Attempt > 1: thêm marker `<!-- attempt n -->` vào cuối tin nhắn user cuối cùng (model_gateway.py:218–223).
- Repair: khi output không khớp schema → tách JSON từ ```json fence → `json.loads` → validate; hỏng →
  `SchemaError("REPAIR_FAILED")`.
- Đo đạc: token = `sum(len(content))//4` (đếm ký tự, xem 2.8 §1); cost fallback $0.01/1k tokens
  (model_gateway.py:167–168) — heuristic, không phản ánh bảng giá từng model; provider trả usage thật
  thì dùng usage thật để settle.
- Budget hook cấp-call: `max_total_tokens / max_total_cost_usd / max_calls` → `BudgetExceededError`.

**Chú ý về giới hạn output:** `ASTRA_MULTI_MAX_OUTPUT_TOKENS` (2000) **chỉ dùng cho ước lượng budget**
(graph.py:157–184); nó **không** được truyền vào OpenAI/Google khi call thật (providers.py:190–192, :233).
Không có cap output 2000 như tài liệu v1 tưởng — lỗi này đã sửa trong bảng hằng số (§15).

---

## 11. Persistence & đồng thời — phần "tin được" và phần "được tô hồng"

- SQLite một connection (timeout 10, `foreign_keys=ON, journal_mode=WAL, synchronous=FULL`);
  `_tx_lock = threading.Lock()` cho **ghi** (BEGIN IMMEDIATE); **đọc không qua lock** và nhiều thread cùng
  dùng một connection (worker thread, SSE poll, API request threads) — sqlite3 không cam kết thread-safety
  cho connection chia sẻ không serialize (2.3 §1).
- Bảng: `runs (id, revision, state_json)`; `events (run_id, sequence, event_json)`; `operations (run_id,
  node, logical_operation_id, operation_json)`; `leases (run_id PK, owner, token, epoch, expires_at)`;
  `app_settings`; `provider_configs`. Migration qua `PRAGMA user_version`.
- Commit pipeline (`commit`): request_hash = sha256(command JSON) → `_check_lease` → operation đã có:
  hash trùng → trả lại record cũ (retry an toàn), khác → `OperationConflict` → `apply_mutation` thuần
  domain → kiểm artifact refs đọc được → `UPDATE runs … WHERE revision=?` (optimistic) — rowcount ≠ 1 →
  `RevisionConflict` → insert event (sequence=max+1) + operation record; kiểm lease lần nữa sau commit.
- **"Event-sourcing" (không đúng nghĩa):** events là **log kèm theo**, không có replay; state là JSON blob
  ghi đè cả cục mỗi commit. Cơ chế này đảm bảo idempotency + audit, không tái dựng được state (2.4 §1).
- Lease fencing: `Lease{token=uuid4, epoch}`; `acquire` epoch+1; `heartbeat` chỉ refresh `expires_at`;
  `release` hết hạn ngay; writer giữ lease cũ (epoch cũ) không commit được. `TERMINAL` từ chối lease trừ
  `PARTIAL` cho `quality-service` (finalize). Worker TTL 300s / heartbeat 30s / failure lease 30s.
- Artifact store content-addressed SHA-256: `put` → hash làm tên file, ghi qua temp + `fsync` +
  `os.replace`; `read` kiểm cả size lẫn hash. **Xoá run không xoá artifacts, không GC** — manifest/
  snapshot/evidence có thể giữ nguyên mãi (1.10 §1) — đáng chú ý vì artifact có thể chứa dữ liệu nhạy cảm.
- `CheckpointBridge`: checkpoint của LangGraph không được đi vượt canonical domain state (load sẽ raise
  `RevisionConflict` nếu checkpoint ahead).

---

## 12. Bảo mật — mô hình thật của nó (chương bổ sung theo các phát hiện đã kiểm chứng)

Tổng hợp bằng chứng (đã kiểm mỗi dòng):

- **Bề mặt auth:**
  - Middleware chỉ khớp prefix `/api/runs` (app.py:112) — bảo vệ run data.
  - `/api/auth/*` công khai theo thiết kế (setup/login).
  - `/api/settings/*` được bảo vệ theo từng route `Depends(require_admin)` (routes_auth_settings.py:394, 415, 434,
    467, 482, 494, 568, 607, 655, 681).
  - **Lỗ thật:** `require_admin` trả `None` khi chưa có admin hash (routes_auth_settings.py:316–318) — trước
    setup, mọi endpoint settings (lưu provider, LƯU API KEY, role mapping kèm API key riêng, test connection)
    đều mở; setup là first-come-first-served. Nếu chạy server lên mạng chung trước khi setup → người lạ
    sở hữu hệ thống (vấn đề này chưa có regression test — nên viết).
- **Crypto & token:** PBKDF2-SHA256 **100k** vòng (thấp hơn khuyến nghị OWASP 2023 ~600.000 cho SHA-256 —
  crypto.py:34); token 2-part HMAC tự chế (crypto.py:88–109), stateless, **không revoke** (`jti` không được
  đối chiếu ở bất cứ đâu),
  hạn 7 ngày; change-password không rotate secret (404–407); không rate-limit login; `?token=` đi qua URL
  (api.ts:450–452) — rủi ro leak qua access logs/history/referer/extension; EventSource không set header
  được là động cơ thật, nhưng cookie httpOnly hay fetch-stream là phương án tốt hơn.
- **SSRF:** `/settings/providers/test` gọi đến `base_url` do admin nhập; hợp đồng cho phép HTTP cho
  loopback (provider_config.py:50–55). Sau setup: cần admin. Trước setup: mở (mục trên). **DocumentFetcher
  thì khác**: HTTPS bắt buộc ngoài loopback (`allow_loopback_http=False` mặc định, documents.py:19+44–48)
  và chỉ chấp nhận URL trong scope prefix — nhưng vẫn có HTTPS tới host bất kỳ trong scope.
- **Data exfiltration qua repo:** hiện **không có đường chạy thật nào** gửi nội dung repo ra ngoài:
  snapshot không được capture trong workflow, ToolBroker không dùng được khi thiếu snapshot (3.5 §1);
  `snapshot_path` là field chết (1.8 §1). Khi những mảnh này được đấu nối (đây là ý định thiết kế),
  không có secret scanning nội dung → key hard-code trong config.js sẽ đi kèm bundle. Rủi ro là latent,
  không phải live.
- **Tính riêng tư master key:** Fernet master key nằm trong bảng `app_settings` của chính SQLite
  (crypto.py:45–52). Mã hoá API key trong DB chỉ có giá trị nếu kẻ xâm nhập chụp được từng phần rời rạc
  (ví dụ trích `provider_configs` mà không có `app_settings`); với kẻ có quyền đọc DB, key nằm ngay cạnh
  ciphertext. Threat model local là nói thật; quảng cáo "không lộ secret" là quá lời.
- **Nhà cung cấp mặc định:** `xkiro` active (routes_auth_settings.py:292–305) — code và README mặc định rót
  nguồn code + yêu cầu khách hàng qua gateway bên thứ ba ("xKiro… OpenRouter-compatible") vì dùng model
  `:free`. Câu hỏi "ai vận hành/log bao lâu/ToS" nằm ngoài code — nhưng việc để gateway bên thứ ba làm
  mặc định mà không yêu cầu người dùng đồng ý rõ ràng là quyết định nên sửa; nên đổi seed.
- **Retention:** delete run giữ artifacts (1.10 §1) — không GC, không TTL.
- **SSE auth token trên URL (1.5 §1).**
- **Sửa tối thiểu khuyến nghị (nếu giữ thiết kế):** (a) `require_admin` raise thay vì return None khi
  chưa setup + `/auth/setup` chỉ nhận khi có bind token in ra console lần đầu; (b) rate-limit login
  (thuần in-process counter đủ); (c) rotate `auth_secret_key` khi change-password; (d) PBKDF2 tăng ≥600k;
  (e) bỏ `?token=`, chuyên cookie httpOnly (thêm fallback fetch-stream); (f) GC artifacts theo reference
  age; (g) đổi seed provider mặc định (giới hạn gateway bên thứ ba làm mặc định); (h) secret-scan nội dung
  snapshot trước khi bundle nếu snapshot được đấu nối.

---

## 13. Quality Gates (P4) — Toàn bộ luật + nhận xét

### 13.1. StructuralQualityValidator (gate + `POST /validate`)

| Rule | Nội dung | Nhận định |
|---|---|---|
| RULE-STRUCT-001 | chưa có plan commit | — |
| RULE-REF-001 | step/artifact trỏ requirement không tồn tại | hợp lý |
| RULE-DESIGN-001 | mode design mà không có design artifact | hợp lý |
| RULE-COV-001 | coverage 100% requirements (design mode tính design_artifacts) | hợp lý | 
| RULE-UNIQUE-001 | trùng step ID | hợp lý |
| RULE-DAG-001 | dependency trỏ step không tồn tại | hợp lý |
| RULE-DAG-002 | dependency cycle | hợp lý |
| RULE-DAG-003 | connected: edges ≥ N-1 | ép hướng chuỗi — hợp lý cho plan tuần tự |
| RULE-DAG-004 | N≥3 → tối đa 2 root steps | **áp đặt** — plan 3 dòng song song bị BLOCKER |
| RULE-DAG-005 | N>1 → critical path depth ≥ 2 | **áp đặt** |
| RULE-DAG-006/007 | INTEGRATION cần dependencies + ancestor SETUP | hợp lý nội bộ luồng |
| RULE-DAG-008 | N>1 → cấm step "isolated" | **áp đặt** |
| RULE-ISSUE-001/002 | blocking chưa resolved; warning trở lên còn mở | hợp lý |
| RULE-STEP-001/002 | step thiếu deliverables / completion_criteria | hợp lý |
| RULE-FULFILL-001 | concrete_deliverable ≥15 ký tự, cấm placeholder; verification_method ≥5 | **Goodhart-able**: câu đúng độ dài pass |
| RULE-FULFILL-002 | hình dạng theo `expected_artifact_type` (bảng / tree `├──` / diagram `-->` / code fence) | heuristic — có FP |
| RULE-VAL-001 | NOT_RUN mà có actual/exit_code | hợp lý |
| RULE-TECH-002 | sandbox FAIL không có PASS bù → blocker | hợp lý |
| RULE-TECH-001 | chạy lại truth-table trên plan | phụ thuộc 4-entry hardcode (3.4 §1) |

### 13.2. FinalizationService (5 pillars) — xem §6.5.

### 13.3. Exporter

- `export_json` — schema_version 1: metadata (run/plan_revision/task_revision/snapshot_id/status/…),
  task, decisions, design_artifacts, steps (kèm fulfillments), issues (kèm resolution), evidence
  (`{id, source_type, locator, content_hash, status}`).
- `export_markdown` — 7 chương theo `PLAN_TEMPLATE.md`; escape `<`/`>` chống HTML injection. Đầu ra là
  **tài liệu**: không có bước nào thử plan này lên code thật, tức chưa có gì chứng minh plan chạy được (5 §1).

---

## 14. API — danh mục (auth-tagged)

### Runs (middleware chặn prefix này khi đã setup)

| Method | Path | Ghi chú |
|---|---|---|
| POST | `/api/runs` | tạo run (202); Idempotency-Key; max_rounds 1..10; token/cost/call limits; mode `greenfield\|repo\|design`; parent_run_id (clone) |
| GET | `/api/runs`, `/api/runs/{id}` | list/detail |
| GET | `/api/runs/{id}/events` | SSE; `Last-Event-ID` hoặc `?last_event_id=`; **token qua query** |
| GET | `/runs/{id}/issues` / `/evidence` / `/decisions` / `/logs` | tra cứu |
| GET | `/runs/{id}/plans/{rev}` | một revision kế hoạch |
| POST | `/runs/{id}/answers` | AnswerQuestion (kèm `expected_revision`) |
| POST | `/runs/{id}/resume` | WAITING_FOR_INPUT → RUNNING (thủ công; dùng cho cả recovery sau restart) |
| POST | `/runs/{id}/cancel` | hủy (không ngắt thread graph — mục 2.1 §1) |
| DELETE | `/runs/{id}?force=` | xóa vĩnh viễn; run active cần `force`; **artifacts không xoá** |
| GET | `/runs/{id}/export?format=json\|markdown&revision=` | PlanExporter |
| POST | `/runs/{id}/validate` | P4.1 validator (không đổi trạng thái) |
| POST | `/runs/{id}/finalize` | 5-pillar → FINAL; lease `quality-service` TTL 30 |

### Auth & Settings (auth theo từng route; mở hoàn toàn trước setup — xem §12)

| Method | Path |
|---|---|
| GET | `/api/auth/status` |
| POST | `/api/auth/setup` (first-come), `/api/auth/login`, `/api/auth/change-password`, `/api/auth/logout` (no-op) |
| GET/POST/DELETE | `/api/settings/providers` (+ `/{name}`; `/{name}/activate`) |
| POST | `/api/settings/providers/test` (SSRF surface — §12) |
| GET/POST | `/api/settings/providers/{name}/models` (discovery) · `/api/settings/providers/models` |
| GET/PUT | `/api/settings/roles` |

Lỗi chuẩn envelope `{error:{code, message, correlation_id}}`: `InvalidState→400`, `RevisionConflict→409`,
`LeaseLost→409`. CORS `*` cho mọi origin (kết hợp token-on-query, §12, là thêm một bề mặt lộ token).

---

## 15. Bảng hằng số — đã tách vai trò (sửa mâu thuẫn v1)

| Hằng số | Giá trị | Vai trò thật | Nguồn |
|---|---|---|---|
| `ASTRA_MULTI_MAX_OUTPUT_TOKENS` | **2000** (mặc định) | **Ước lượng budget** `(prompt + 2000) × safety`; KHÔNG truyền vào API provider | graph.py:157–184; providers.py:190–192 (omit), :233 (None) |
| `DEFAULT_ORCHESTRATION_MAX_TOKENS` | **12000 bytes** | limit bundle orchestration; env `ASTRA_MULTI_MAX_CONTEXT_BYTES` | bundle.py:38–39 |
| `ContextLimits.max_tokens` | **16000** | mặc định của dataclass cho lối gọi khác | bundle.py:70 |
| `max_rounds` | 2 (1..10) | số vòng propose→gate | graph.py:1476; API schema |
| `max_intake_retries` | 2 | vòng tự bù cho thiếu deliverables | graph.py |
| `recursion_limit` | 150 | guard LangGraph — không bao giờ chạm với 2 vòng | graph.py compile + worker |
| Lease worker TTL / heartbeat / failure | 300s / 30s / 30s | giữ/chết lease | worker.py |
| Gateway max_retries / timeout gọi | 2 / 120s (max 3600) | retry/backoff | model_gateway.py |
| Backoff retry | `sleep(1s × attempt)` — tuyến tính, không jitter/Retry-After | — | model_gateway.py:379/419/449 |
| Token ước lượng | `sum(len(content))//4` — đếm ký tự, heuristic | đo đạc | model_gateway.py:167 |
| Cost fallback | $0.01/1k tokens | ước lượng budget | model_gateway.py:168, 287 |
| Snapshot quota | 10k file / 4MiB file / 64MiB tổng | lib SnapshotStore — **chưa đấu nối vào workflow** | snapshots.py |
| Sandbox timeout (verifier) | 15s (timeout → exit 124) | chạy script tự sinh trên HOST | verifier.py:314–344 |
| Sandbox profile Docker | 0.1–600s / 256MB / 1 CPU / 64 pids / output 64KiB; `--network none --read-only --cap-drop=ALL --user 65534:65534` | lib — **chỉ demo/tests** | sandbox/runner.py |
| SSE poll | 0.5s / client / 2 queries | nội bộ | worker.py |
| Frontend polling | run details 2.5s active / 2s SSE rớt / 12s idle; list 2.5/6/15s; bỏ khi tab ẩn | — | App.tsx:486, 503 |
| Auth token | HMAC 2 phần, hạn **7 ngày**, không revoke | — | crypto.py:88–109 |
| PBKDF2 | 100.000 vòng (SHA-256) | — | crypto.py:34 |
| DocumentFetcher | timeout 10s, ≤1MiB, redirect ≤3, **HTTPS bắt buộc ngoài loopback** | lib | documents.py |
| Rubric/validator corpus | deliverable ≥15 ký tự; verification ≥5; bundle mức 3 chỉ còn ≤5 issue | dễ Goodhart | quality_validator.py |

---

## 16. Frontend, CLI, scripts/evaluations — với đánh giá trung thực

- **Frontend:** 7 tab + modals; PhaseTracker 11 step; consumer SSE phủ 12 event type; polling an toàn như
  trên; i18n VN/EN (`astra_lang`, VN mặc định); clone qua `parent_run_id` (default token 250k, $5,
  rounds 2 — App.tsx:548/NewRunModal.tsx:59); export download. Dư thừa nổi bật: vừa SSE vừa polling (5.2 §1).
- **CLI** (`python -m astra_multi.cli`): `create / status / logs / answer / cancel / delete / artifacts /
  validate / finalize / serve`; `provider set/list/remove` riêng.
- **Scripts & evaluations:**
  - `scripts/live_minesweeper_run.py` — live run LLM thật, **bắt buộc** `ASTRA_LIVE_LLM=1`, budget cap
    `--budget-cap` (mặc định $1.00), ≤3 runs; ghi `LIVE_RUN.md`.
  - `scripts/measure_prompt_bloat.py` — đo token prompt qua 5 vòng (adapter fake).
  - `scripts/run_architecture_tests_live.py` — TEST1/2/3 sống với key thật.
  - `evaluations/*` — **mô phỏng, không gọi LLM** (multi_agent_runner: token = `min(cap, 4500 + req·680)`;
    baseline: công thức khác, cap 10k vs 15k → **ngân sách không cân bằng**); scoring/report sinh từ dữ
    liệu mô phỏng. Đánh giá (5.1 §1): đây là test pipeline, không phải bằng chứng rằng kiến trúc multi-agent
    + rubric tốt hơn một call model mạnh đơn lẻ — kết luận kiểu đó **chưa được chứng minh trong repo**.
    Không có kết quả sống nào của `live_minesweeper_run` được commit.

---

## 17. Chuỗi sự kiện end-to-end (tổng hợp)

```text
[User] POST /api/runs (goal, reqs, mode, budgets, idempotency-key)
  → classify_all → store.create(+run_created) → ghim role-mapping snapshot
  → worker.start_run → [LEASE 300s] + BudgetService
[Graph trong executor thread — cancel không ngắt được]
  INTAKE: classify + gaps (≤2 retries) → RubricChecklist (code, không LLM)
  SNAPSHOT: STUB — không capture gì trong live workflow
  INVESTIGATE: TechStackTruthTable (4 entry hardcode) + CLAIM-TRUTH-* (claim tự phát)
  INDEPENDENT_ANALYSIS: fan-out planner ∥ reviewer (isolation CHỈ ở phase này)
  PROPOSE → REVIEW (issues id sha256(run:round:claim) + alias-map "ISSUE-1/#1")
  VERIFY: (a) regex anti-pattern (negation 70-chars); (b) script tự sinh chạy trên HOST subprocess
  REVISE: Synthesizer → PlanRevision (DAG + fulfillments ép theo luật) → CommitPlan (rev+1)
  SEMANTIC_REVIEW: reviewer chấm rubric → MET/PARTIAL/MISSING; merge verdicts; record stagnation
  GATE: validator + semantics + coverage + stagnation (vô hiệu điều khiển khi max_rounds=2)
        pass → EXPORT | fail && round<max && !stagnant → PROPOSE (round+1) | else export (PARTIAL)
[ngoài graph]  POST /finalize → 5-Pillar → FINAL (lease quality-service)
[SSE] poll DB 0.5s → event {id, event, data}; transition_run phát đôi transition_phase; run_completed cuối
```

---

## 18. Cần làm gì tiếp (theo thứ tự ưu tiên)

Danh sách ngắn dẫn trực tiếp từ các phát hiện đã kiểm chứng — không phải roadmap đầy đủ, chỉ là thứ tự
ưu tiên:

1. **Cancel thật sự phải ngắt**: chạy graph trong thread có cờ sentinel kiểm tra giữa các node; hoặc
   chuyển sang async LangGraph (`.ainvoke`) để cancel tác động được giữa các call.
2. **Auth**: (a) `require_admin` raise khi chưa setup; (b) `/auth/setup` yêu cầu bind-token được in ra
   console/logs; (c) rate-limit login; (d) rotate `auth_secret_key` khi change-password; (e)
   PBKDF2 ≥600k; (f) bỏ token-query (cookie httpOnly/fetch-stream).
3. **Đấu nối hoặc gỡ bỏ khung scaffold**: snapshot capture, Docker/Windows runner, ToolBroker — 3 bộ khung
   đang làm tài liệu trông "có kiểm chứng" hơn thực tế. Gỡ bỏ hoặc wire-in + regression test.
4. **No-GC artifacts + snapshot giữ secret**: GC theo reference + secret scanning trước khi bundle.
5. **SSE**: single-connection SQLite an toàn nhất là **mỗi luồng một connection (read-only pool)**; SSE
   chuyển sang long-poll hoặc notify; bỏ duplicate event.
6. **Ngân sách cảm nhận thật**: lấy usage thật từ provider để settle; fallback cost phải theo bảng giá
   model; token đếm theo tokenizer-thật (tiktoken) thay vì `chars//4`.
7. **Backoff**: jitter + Retry-After; sửa comment "Exponential" thành tuyến tính hoặc làm exponential.
8. **Issue id**: chuyển sang nhận diện ổn định qua các vòng (ví dụ hash trên claim đã canonicalize +
   ID khái niệm do vòng đầu tiên cấp), hoặc bỏ `round` khỏi hash; sau đó dần bỏ heuristic `res_alias_map`.
9. **Rubric review độc lập**: chấm rubric bằng model khác Planner (ép buộc, không chỉ cảnh báo), hoặc
   tăng phần chấm bằng checker deterministic; nguy cơ tương quan lỗi còn là UI cảnh báo — nên cấm.
10. **Benchmark sống**: một experiment công bằng — cùng đề, cùng ngân sách: live run của Astra vs một call
    model mạnh đơn lẻ; commit kết quả + báo cáo phương pháp. Cho tới khi có nó, README không nên tuyên bố
    "giải quyết triệt để".
11. **Stagnation + max_rounds**: gắn stagnation vào quyết định loop (phát signal giữa vòng, hoặc đổi giá trị
    mặc định của `max_rounds`); hiện tại nó là dead control-flow với mặc định.
12. **Output repair/PARTIAL**: phân biệt `infra_error` (lỗi hạ tầng thật sự) với "model chưa hoàn tất"
    để stop_reason trỏ đúng; không gộp mọi lỗi vào "PARTIAL".

---

## 19. Phạm vi kiểm chứng của tài liệu này

- **Tự kiểm (có file:line như trên):** auth scope/require_admin/setup/login/change-password/key-storage;
  PBKDF2; token format; crypto key storage; delete/keep artifacts; worker executor/cancel/lifespan; SSE
  duplicate + query-token; sqlite connection/lock/events/get_run_status_info; gateway estimates/backoff/
  marker/overflow-half; providers max_tokens pass-through; graph edges, gate, export/status logic,
  snapshot_node stub, verify_node caller, alias-map, stagnation timing + should_loop; bundle 12000/16000;
  api.ts query token; App.tsx polling; evaluations caps/formulas (simulated); contract_extractor rubric
  sinh code; DocumentFetcher loopback default; provider base_url contract; xKiro seed active.
- **Tự tin dựa trên hai báo cáo khám phá khớp nhau (chưa tự đọc từng dòng):** các flag Docker/Windows
  runner cụ thể, chi tiết degrade 4 mức theo thứ tự, chi tiết seed providers, các giá trị polling đã liệt kê.
- **Không kiểm chứng:** ToS/retention của nhà cung cấp thứ ba; hiệu năng sống; kết quả LLM thật.
