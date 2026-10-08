# Báo Cáo Thẩm Định Độc Lập Kiến Trúc Backend (VERIFY.md)

**Ngày thẩm định:** 07/10/2026  
**Vai trò:** Reviewer Độc Lập (Independent Senior Backend Reviewer)  
**Phạm vi:** Kiểm toán và xác minh 8 phát hiện lỗi F-001 đến F-008 từ `docs/audit/BACKEND_AUDIT.md`, `git log`, `git diff` từ commit `dbbb769` đến `HEAD` (`cd45f19`).

---

## 1. Bảng Tổng Hợp Thẩm Định (Finding Verification Table)

| Finding ID | Mức độ | Trạng thái | Bằng chứng gốc & Lỗi ban đầu | Test mới đã thêm | Kết quả Revert Test |
| :--- | :--- | :---: | :--- | :--- | :--- |
| **F-001** | Critical | **PASS** | `orchestration/graph.py`: Mũi tên từ Gate quay về `review` thay vì `propose`, khiến Proposal không bao giờ được làm mới ở vòng lặp sau. | `test_f001_multi_round_calls_propose_each_round` | **FAILED** (`assert 1 == 2`: `propose_node` chỉ được gọi 1 lần khi revert về `review`). |
| **F-002** | Critical | **PASS** | `orchestration/graph.py`: Thiếu command `ChangeIssue`, các blocking issue vĩnh viễn ở trạng thái `OPEN`, Gate luôn từ chối cấp `FINAL`. | `test_f002_blocking_issue_resolved_by_independent_reviewer`, `test_f002_minesweeper_fixture_resolves_blocker_and_finalizes_by_p4` | **FAILED** (`AssertionError: Gate failed with: Max review/revise rounds reached: 1 unresolved blocking issues; [RULE-ISSUE-001]`). |
| **F-003** | High | **PASS** | `orchestration/graph.py`: `propose_node` tự động spoof 100 ký tự đầu của `approach` vào `requirement_coverage` khi LLM bỏ sót; `revise_node` tự điền cứng `deliverables` / `criteria`. | `test_f003_no_spoofing_when_llm_omits_coverage` | **FAILED** (`AssertionError: assert {'REQ-002': '...'} == {}`: dữ liệu bị spoof khi revert code). |
| **F-004** | High | **PASS** | `orchestration/budget.py`: `reserve` không retry khi gặp `RevisionConflict`; `settle`/`release` chỉ đổi in-memory không commit DB; `graph.py` không gọi budget service. | `test_f004_budget_counters_match_recalculated_totals`, `test_f004_budget_service_persists_settle_and_release_across_restart`, `test_f004_budget_concurrent_threads_reserve_success`, `test_f004_graph_budget_integration_settles_and_releases_without_leak` | **FAILED** (`assert 0 == 850`: token/cost bị reset về 0 sau khi restart service nếu thiếu persistence DB). |
| **F-005** | Medium | **PASS** | `orchestration/graph.py`: Dùng `uuid.uuid4().hex` trực tiếp trong node khiến chạy lại sinh ID ngẫu nhiên, vi phạm Idempotency. | `test_f005_idempotent_nodes_no_duplicate_proposals_or_issues` | **FAILED** (`AssertionError: Expected 1 proposal, found 2`: nhân bản Proposal khi revert về `uuid4`). |
| **F-006** | Medium | **PASS** | `orchestration/graph.py`: `review_node` lặp qua toàn bộ `curr_state.tasks`, làm sống lại các requirement đã bị xóa ở task revision mới nhất. | `test_f006_review_node_ignores_deleted_requirements` | **FAILED** (`AssertionError: assert 'REQ-DELETED' not in ['REQ-DELETED', 'REQ-001']`). |
| **F-007** | Medium | **PASS** | `orchestration/graph.py`: `revise_node` liên tục tạo Decision mới ở mỗi vòng lặp mà không có cơ chế tái sử dụng hoặc supersede, làm phình to state. | `test_f007_active_decisions_do_not_balloon_across_n_rounds`, `test_f007_superseded_decision_replaces_old_in_active_plan` | **FAILED** (`AssertionError: assert 2 == 1`: quyết định trùng bị nhân bản khi revert cơ chế reuse). |
| **F-008** | High | **PASS** | `orchestration/graph.py`: `quality_gate_node` chỉ kiểm tra thủ công, không gọi `StructuralQualityValidator`, bỏ lọt chu trình DAG trong plan. | `test_f008_quality_gate_detects_dag_cycle` | **FAILED** (`assert True is False`: Gate cho phép lọt Plan có chu trình DAG khi revert validator). |

---

## 2. Kiểm Tra Tính Toàn Vẹn Hệ Thống (Integrity & Invariant Checks)

### 2.1. Kiểm tra mã nguồn (Codebase Hygiene)
- **Không còn `uuid4` trong LangGraph nodes:** Đã kiểm tra toàn bộ file `backend/src/astra_multi/orchestration/graph.py` qua lệnh quét tĩnh. Không còn bất kỳ lời gọi `uuid.uuid4()` nào. Tất cả ID thực thể (`Proposal`, `Issue`) đều sử dụng hàm băm tất định `uuid.uuid5(uuid.NAMESPACE_URL, f"{run_id}:{round}:{node}:{idx}")`.
- **Không còn logic spoofing / tự điền dữ liệu:** Đã xóa bỏ toàn bộ fallback gán `approach[:100]` cho `requirement_coverage` tại `propose_node` và fallback `["deliverable.py"]`, `["tests pass"]` tại `revise_node`. Thiếu sót từ LLM được giữ nguyên để Gate chặn và kích hoạt vòng lặp hiệu chỉnh.
- **Thứ tự 11 pha & ADR Semantic Review:** Thêm pha `SEMANTIC_REVIEW` giữa `REVISE` và `QUALITY_GATE` (theo ADR đã duyệt) đảm bảo Reviewer độc lập đánh giá bản Plan mới nhất và đóng issue trước khi bước vào Gate (nâng tổng số pha từ 10 lên 11).
- **Kiểm tra bộ Test Suite (Test Suite Invariants)**:
- **Số lượng test bị xóa / sửa yếu:** **0 test bị xóa, 0 test bị làm yếu.** Duy nhất 1 dòng thay đổi import trong `test_orchestration_workflow.py`.
- **Skip / Xfail mới:** **0 skip/xfail mới.** Toàn bộ 13 test `SKIPPED` là các test môi trường có từ baseline ban đầu (6 test yêu cầu live Docker sandbox, 4 test yêu cầu API key OpenAI/Google thực tế, 3 test tính năng hệ điều hành đặc thù POSIX FIFO/symlink/case-sensitive trên Windows).
- **Kết quả chạy full suite:**
  ```text
  386 passed, 13 skipped, 2 warnings in 24.11s (100% PASS, 0 FAIL)
  ```

---

## 3. Chạy Mô Phỏng Thực Tế: Minesweeper Run (Fake LLM)

Kịch bản kiểm thử tích hợp vòng lặp đa tác nhân Minesweeper (`REQ-001: Grid allocation`, `REQ-002: Mine distribution`):
- **Vòng 1:**
  - `propose`: Đưa ra tiếp cận PRNG.
  - `review`: Phát hiện lỗi blocker `Mine placement lacks deterministic seed support` (`IssueSeverity.BLOCKING`).
  - `revise`: Tạo `PlanRevision 1` (chưa xử lý seed).
  - `semantic_review`: Đánh giá issue chưa giải quyết (`resolutions=[]`).
  - `quality_gate`: **FAILED** do tồn tại blocking issue.
  - `should_loop_or_export`: Chuyển hướng quay lại **`propose`**.
- **Vòng 2:**
  - `propose`: Gọi lần 2, sinh proposal mới.
  - `review`: Không phát hiện issue mới.
  - `revise`: Tạo `PlanRevision 2` bổ sung seedable PRNG cho STEP-2.
  - `semantic_review`: Reviewer độc lập đánh giá `PASS`, gọi `ChangeIssue` chuyển issue thành `RESOLVED`.
  - `quality_gate`: **PASSED** (0 blockers, 100% requirement coverage, DAG hợp lệ).
  - `export` & `P4-quality-service`: Chứng nhận chất lượng và cấp trạng thái **`FINAL`**.

**Kết quả ghi nhận:**
```text
Minesweeper simulation:
- propose_calls: 2 (gọi đúng 2 lần ở 2 vòng lặp)
- gate_passed: True
- final_status: FINAL
- unresolved_blockers: [] (0 blocker tồn đọng)
```

---

## 4. Các Rủi Ro Kỹ Thuật Còn Lại (Residual Risks)

1. **Phình to Token Prompt (Prompt History Bloat):**
   - Hiện tại toàn bộ lịch sử `model_calls` và `events` được nạp vào context bundle qua các vòng lặp. Với các tác vụ phức tạp chạy 3–5 vòng, kích thước prompt gửi tới LLM sẽ tăng nhanh. Cần xem xét áp dụng chiến lược tóm tắt (summarization) hoặc sliding window cho context ở các phiên bản tiếp theo.
2. **Ước lượng Ngân sách cố định (Static Budget Reservation):**
   - Tại `graph.py`, `_call_model_with_budget` đang tạm ước tính 4.000 tokens ($0.04 USD) trước khi gọi LLM rồi settle theo số thực tế. Đối với các prompt có context rất lớn (>4.000 tokens), reservation có thể thấp hơn mức tiêu thụ thực tế tức thời trước khi settle.
3. **Môi trường Windows Runner Limitations:**
   - Một số test sandbox Docker và filesystem nâng cao (POSIX FIFO, symlinks không cấp quyền SeCreateSymbolicLinkPrivilege) được skip đúng quy định trên Windows native. Khi triển khai CI/CD Linux runner, các biến môi trường này sẽ cần được kích hoạt đầy đủ.

---

## 5. Kết Luận
Tất cả 8 phát hiện lỗi **F-001 đến F-008** đã được sửa chữa triệt để, bảo toàn nghiêm ngặt các invariant cốt lõi của hệ thống, vượt qua 100% test suite và được kiểm chứng độc lập thành công.
Hệ thống sẵn sàng cho bước tiếp theo.
