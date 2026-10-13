# BÁO CÁO NGHIỆM THU: CẢI THIỆN CHẤT LƯỢNG KẾ HOẠCH ASTRA MULTI (A..G)

Tài liệu này đối chiếu và xác minh toàn bộ các yêu cầu từ `AGENT_PROMPT_FIX_PLAN_QUALITY.md` qua hai giai đoạn:
- **Phase 1**: Cổng chất lượng phải nói thật (Mục A, B, C)
- **Phase 2**: Để plan chứa được thiết kế kỹ thuật (Mục D, E, F, G)
- **Nghiệm thu tổng thể**: Suite xanh 100%, Minesweeper đạt `FINAL`, Test 7 chạy lại trong mode `design` đạt `FINAL`.

---

## 1. Bảng đối chiếu hạng mục A .. G

| Mục | Yêu cầu | Commit | Kết quả | Bằng chứng kiểm thử | Kiểm tra fail khi revert (git stash) |
|---|---|---|---|---|---|
| **[A]** | Finalize không hardcode `passed=True`; persist kết quả semantic review vào store | `51b6f5f` | **PASS** | `test_phase1_finalize_semantic_review.py` (4/4 passed) | Khi revert: API & CLI tự tạo `passed=True`, không kiểm tra store, test fail. |
| **[B]** | `RULE-ISSUE-002` chặn mở Warning/Blocker; stop reason tiếng Việt khi hết lượt | `f061d3c` | **PASS** | `test_phase1_rule_issue_002.py` (4/4 passed) | Khi revert: Quality report bỏ qua warning issues, `passed=True` sai sự thật. |
| **[C]** | Bỏ validator tự điền dữ liệu giả; báo lỗi schema thay vì bịa ID/bước giả | `7c2d238` | **PASS** | `test_phase1_no_spoofing.py` (5/5 passed), grep 0 kết quả dữ liệu giả | Khi revert: Dữ liệu rỗng tự động điền `Deliverable artifact`, không bắn ValidationError. |
| **[D]** | Intake nhận constraints, non-goals, expected outputs; acceptance tiếng Việt | `7d6099a` | **PASS** | `test_phase2_d_intake.py` (2/2 passed) | Khi revert: Schema intake thiếu trường, expected outputs không chuyển thành REQ. |
| **[E]** | Thêm Design Artifacts, mode "design", `RULE-DESIGN-001`, mục 4 "Thiết kế" exporter | `7128f62` | **PASS** | `test_phase2_e_design_mode.py` (5/5 passed) | Khi revert: Thiếu `DesignArtifactDraft`, thiếu `RULE-DESIGN-001`, export thiếu mục 4. |
| **[F]** | Semantic Review ánh xạ sang reviewer độc lập, thỏa mãn chính sách command actor | `be1b3fc` | **PASS** | `test_phase2_f_semantic_independence.py` (3/3 passed) | Khi revert: `semantic_review` map vào `synthesizer`, vi phạm tính độc lập thẩm định. |
| **[G]** | Reviewer chấm theo từng requirement verdict, hỗ trợ resolution `DUPLICATE` | `b676d80` | **PASS** | `test_phase2_g_requirement_verdicts.py` (4/4 passed) | Khi revert: Thiếu `RequirementVerdict`, `DUPLICATE` không chuyển trạng thái hợp lệ. |

---

## 2. Chi tiết kết quả kiểm tra từng hạng mục

### [A] Finalize không hardcode `passed=True`
- **Thay đổi chính:**
  - Thêm phương thức `save_semantic_review` và `get_semantic_review` vào `SQLiteStore` và `WorkflowRepository`.
  - Node `semantic_review_node` tính toán `SemanticReviewAssessment` dựa trên số lượng issue thực tế và lưu vào store.
  - `finalize_run` trong `api/app.py` và `cli.py` đọc đánh giá đã lưu từ store; nếu không có kết quả hoặc kết quả bị lệch revision, hạ trạng thái xuống `PARTIAL`.
- **Lệnh kiểm chứng:**
  ```powershell
  python -m pytest tests/unit/test_phase1_finalize_semantic_review.py
  ```
  *Kết quả: 4 passed.*

### [B] RULE-ISSUE-002: Kiểm soát issue mức WARNING
- **Thay đổi chính:**
  - `StructuralQualityValidator` kiểm tra mọi issue có severity `BLOCKING` hoặc `WARNING` với trạng thái `OPEN`, `INVESTIGATING`, `PROPOSED_RESOLUTION` và tạo blocker violation.
  - Remediation chuẩn: *"Giải quyết, từ chối hoặc đánh dấu trùng (DUPLICATE) mọi issue warning trở lên"*.
  - `quality_gate_node` và `export_node` trong `graph.py` hạ trạng thái về `PARTIAL` kèm stop_reason tiếng Việt nêu rõ số issue còn lại khi hết max rounds.
- **Lệnh kiểm chứng:**
  ```powershell
  python -m pytest tests/unit/test_phase1_rule_issue_002.py
  ```
  *Kết quả: 4 passed.*

### [C] Loại bỏ validator tự điền dữ liệu giả (Anti-Spoofing)
- **Thay đổi chính:**
  - Xóa bỏ việc tự điền `["REQ-001"]`, `"Deliverable artifact"`, `"Completion verified"` trong `agents/roles.py`.
  - `SynthesizerOutput.normalize_issues_addressed` chỉ trích xuất regex `ISSUE-xxx`, raise `ValidationError` nếu gặp chuỗi không hợp lệ, không tự sinh `"ISSUE-{idx+1}"`.
- **Lệnh kiểm chứng:**
  ```powershell
  python -m pytest tests/unit/test_phase1_no_spoofing.py
  git grep -E "Deliverable artifact|Completion verified" backend/src/
  ```
  *Kết quả: 5 passed; grep không tìm thấy bất kỳ chuỗi tự điền nào trong `src/`.*

### [D] Intake nhận ràng buộc, đầu ra mong muốn và acceptance thật
- **Thay đổi chính:**
  - Mở rộng `CreateRunRequest` và `cmd_create` nhận: `constraints: list[str]`, `non_goals: list[str]`, `expected_outputs: list[str]`.
  - Mỗi `expected_output` được ánh xạ thành một `Requirement` tuần tự (`REQ-xxx`) để bắt buộc `RULE-COV-001` phải bao phủ.
  - Acceptance mặc định sử dụng format tiếng Việt: *"Plan nêu cơ chế cụ thể đáp ứng yêu cầu này và cách kiểm chứng: <req.text>"*.
- **Lệnh kiểm chứng:**
  ```powershell
  python -m pytest tests/unit/test_phase2_d_intake.py
  ```
  *Kết quả: 2 passed.*

### [E] Design Artifacts + Mode "design"
- **Thay đổi chính:**
  - Thêm `DesignArtifactDraft` vào `agents/roles.py` với các loại: `state_machine`, `message_schema`, `stop_conditions`, `recovery_protocol`, `failure_modes`, `sequence_flow`.
  - Mở rộng domain model `PlanRevision` với trường `design_artifacts: list[DesignArtifact]`.
  - Thêm mode `"design"` cho `Run`: Synthesizer tập trung sinh `design_artifacts` phủ mọi requirement, các bước `steps` chỉ đóng vai trò kế hoạch kiểm chứng/triển khai tối thiểu.
  - Bổ sung `RULE-DESIGN-001` (chặn khi mode design thiếu artifact) và cập nhật `RULE-COV-001` tính cả requirement trong design artifacts.
  - Exporter sinh mục `## 4. Thiết kế` (Markdown bảng mô tả và JSON representation).
- **Lệnh kiểm chứng:**
  ```powershell
  python -m pytest tests/unit/test_phase2_e_design_mode.py
  ```
  *Kết quả: 5 passed.*

### [F] Semantic Review độc lập với Synthesizer
- **Thay đổi chính:**
  - Ánh xạ `ROLE_GROUP["semantic_review"] = "reviewer"`.
  - Đảm bảo agent Reviewer đánh giá độc lập bản kế hoạch do Synthesizer tạo ra.
  - Kiểm tra ràng buộc chính sách `IssueResolution.reviewer != command.actor` được bảo đảm thông qua `WorkflowController` (actor=`orchestration-controller`, reviewer=`reviewer`).
- **Lệnh kiểm chứng:**
  ```powershell
  python -m pytest tests/unit/test_phase2_f_semantic_independence.py
  ```
  *Kết quả: 3 passed.*

### [G] Reviewer chấm theo RequirementVerdict & Hỗ trợ DUPLICATE
- **Thay đổi chính:**
  - Thêm `RequirementVerdict` (`PASS`, `PARTIAL`, `FAIL`, `gap`) và trường `requirement_verdicts` vào `ReviewOutput`.
  - Cập nhật prompt Reviewer hướng dẫn diễn đạt lại yêu cầu, chỉ ra cơ chế và phán xét kết luận.
  - Mở rộng `IssueResolutionReport` hỗ trợ `review_result="DUPLICATE"` và `duplicate_of`. `WorkflowController` chuyển issue trực tiếp sang `IssueStatus.DUPLICATE`.
  - Cập nhật cách tính `SemanticReviewAssessment.passed`: bắt buộc không còn issue Warning/Blocker mở VÀ 100% `requirement_verdicts` đạt `PASS`.
- **Lệnh kiểm chứng:**
  ```powershell
  python -m pytest tests/unit/test_phase2_g_requirement_verdicts.py
  ```
  *Kết quả: 4 passed.*

---

## 3. Nghiệm thu tổng thể (Acceptance Tests)

### 3.1. Full Test Suite
Chạy toàn bộ 520 test trong thư mục `backend/tests`:
```powershell
python -m pytest
```
- **Kết quả:** `506 passed, 14 skipped, 0 failed, 0 xfail` trong 63 giây.
- **Ghi chú:** 14 skipped là các bài test môi trường cô lập yêu cầu Docker Sandbox daemon hoặc mạng bên ngoài (preexisting), không phát sinh bất kỳ skip/xfail mới nào.

### 3.2. Minesweeper Fake LLM Regression Test
Chạy kịch bản Minesweeper 5 vòng lặp:
```powershell
python -m pytest -v tests/unit/test_p54_prompt_bloat.py -k test_p54_minesweeper_5rounds_bloat_reduction_and_final
```
- **Kết quả:** `PASSED`.
- **Xác nhận:**
  - Run đạt trạng thái cuối cùng: `RunStatus.FINAL` tại phase `RunPhase.EXPORT`.
  - Gate passed: `True`.
  - Số lượng token prompt giảm đáng kể so với baseline trước đó (Planner <= 900, Reviewer review <= 1000, Semantic Review <= 1200).

### 3.3. Test 7 Chạy lại trong Mode "Design"
Chạy kịch bản Test 7 (thiết kế engine đa agent Planner/Worker/Reviewer) với đầy đủ constraints, non-goals và expected_outputs:
```powershell
python -m pytest -v tests/integration/test_test7_design_mode.py
```
- **Kết quả:** `PASSED`.
- **Xác nhận:**
  - Mode: `"design"`.
  - Toàn bộ 7 requirements (4 ban đầu + 3 expected outputs) được phủ đầy đủ bởi các `design_artifacts`:
    1. `Engine State Machine & Phase Transitions` (`state_machine`)
    2. `Inter-Agent Communication Contracts` (`message_schema`)
    3. `Worker Crash Recovery & Lease Heartbeat` (`recovery_protocol`)
    4. `Budget Enforcement and Round Limits` (`stop_conditions`)
    5. `Append-Only Audit Log and Persistence` (`sequence_flow`)
  - Semantic review trả về 100% `RequirementVerdict` là `PASS` và 0 open issues.
  - FinalizationService chứng nhận `can_finalize=True` và `target_status=FINAL`.
  - Exporter sinh đầy đủ mục `## 4. Thiết kế` và trường `design_artifacts` trong file JSON.

---

## 4. Rủi ro còn lại & Đề xuất

1. **Khả năng sinh JSON của LLM thực tế:**
   - Trong môi trường thực với LLM ngoài (Gemini/OpenAI/Claude), khi ở chế độ `design`, schema `SynthesizerOutput` có thêm `design_artifacts` với `min_length=1` cho `requirement_ids`. Cần đảm bảo context builder phân bổ đủ token completion (tối thiểu 2000 tokens) để model không bị cắt cụt nội dung artifact.
2. **Quản lý kích thước Prompt khi có nhiều Design Artifacts lớn:**
   - Các artifact dạng chuỗi dài (như schema lớn hoặc sequence flow chi tiết) có thể làm tăng token ở các vòng lặp sau nếu kế hoạch sửa đổi liên tục. Cơ chế tóm tắt vòng cũ trong `ContextBuilder` nên tiếp tục được theo dõi nếu số round vượt quá 4.
