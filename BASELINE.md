# BASELINE AUDIT REPORT — ASTRA MULTI BACKEND

**Thời điểm lập:** 2026-10-07  
**Mục tiêu:** Thiết lập baseline toàn diện hiện trạng hệ thống Astra Multi, đối soát mã nguồn thực tế với `docs/audit/BACKEND_AUDIT.md`, kiểm chứng invariants và đánh giá độ bao phủ test suite trước khi thực hiện các giai đoạn sửa đổi.  
**Nguyên tắc:** Lập baseline, KHÔNG sửa mã nguồn.

---

## 1. Kết quả chạy Full Test Suite

- **Môi trường thực thi:** Windows native, Python 3.11.7, pytest 9.1.1, pluggy 1.6.0.
- **Lệnh thực thi:** `backend\.venv\Scripts\pytest.exe` (thư mục `backend`).
- **Tổng số test:** 365 test items.
- **Kết quả:**
  - **352 PASSED** (96.4%)
  - **0 FAILED** (0.0%)
  - **13 SKIPPED** (3.6% — các sandbox test yêu cầu Docker/Linux container và live provider tests không có API key)
  - **2 WARNINGS** (deprecation warnings từ pydantic và langchain_core)
  - **Thời gian chạy:** ~32 giây.

### Phân bố chi tiết theo module test:
| File kiểm thử | Passed | Skipped | Failed |
| :--- | :---: | :---: | :---: |
| `tests/integration/test_api.py` | 8 | 0 | 0 |
| `tests/integration/test_auth_settings.py` | 2 | 0 | 0 |
| `tests/integration/test_evidence_context.py` | 3 | 0 | 0 |
| `tests/integration/test_orchestration_workflow.py` | 3 | 0 | 0 |
| `tests/integration/test_p2_demo.py` | 1 | 0 | 0 |
| `tests/integration/test_sandbox.py` | 6 | 6 | 0 |
| `tests/integration/test_storage.py` | 14 | 0 | 0 |
| `tests/recovery/test_crash.py` | 6 | 0 | 0 |
| `tests/recovery/test_invariants.py` | 6 | 0 | 0 |
| `tests/support/p2_repo/fixture_test.py` | 1 | 0 | 0 |
| `tests/test_checkpoint.py` | 6 | 0 | 0 |
| `tests/test_providers.py` | 5 | 4 | 0 |
| `tests/test_recovery.py` | 4 | 0 | 0 |
| `tests/test_workflow.py` | 10 | 0 | 0 |
| `tests/unit/test_agents.py` | 6 | 0 | 0 |
| `tests/unit/test_budget_and_controller.py` | 5 | 0 | 0 |
| `tests/unit/test_bundle_overflow_fix.py` | 3 | 0 | 0 |
| `tests/unit/test_cli.py` | 4 | 0 | 0 |
| `tests/unit/test_domain.py` | 186 | 0 | 0 |
| `tests/unit/test_evaluations.py` | 3 | 0 | 0 |
| `tests/unit/test_gateway.py` | 14 | 0 | 0 |
| `tests/unit/test_gateway_retry.py` | 14 | 0 | 0 |
| `tests/unit/test_provider_settings.py` | 22 | 0 | 0 |
| `tests/unit/test_quality_and_export.py` | 6 | 0 | 0 |
| `tests/unit/test_snapshots.py` | 9 | 3 | 0 |
| `tests/unit/test_sqlite_initialization.py` | 3 | 0 | 0 |
| `tests/unit/test_tool_broker.py` | 4 | 0 | 0 |
| **TỔNG CỘNG** | **352** | **13** | **0** |

> **Nhận định:** Mặc dù 100% test đang chạy đều PASS, hệ thống thực tế vẫn chứa đầy đủ các lỗi nghiêm trọng về luồng điều phối đa tác nhân (Multi-Agent Loop) do test suite hiện tại chưa bao phủ các kịch bản loop thực tế (mock quá nông, bỏ qua propose khi lặp, hoặc không sinh issue).

---

## 2. Đối soát tình trạng các Finding F-001..F-008 trong mã nguồn thực tế

Đối chiếu từng mục trong `docs/audit/BACKEND_AUDIT.md` trực tiếp với mã nguồn hiện tại:

| Finding ID | Mức độ | Trạng thái trong Audit | Tình trạng thực tế | Vị trí file và dòng code hiện tại | Chi tiết xác nhận & Chênh lệch (nếu có) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **F-001** | Critical | VERIFIED | **TỒN TẠI** | `backend/src/astra_multi/orchestration/graph.py:484, 517` | `should_loop_or_export` trả về `"review"` thay vì `"propose"`. Cạnh điều kiện `gate` trỏ `"review": "review"`. Proposal không bao giờ được cập nhật khi lặp vòng. |
| **F-002** | Critical | VERIFIED | **TỒN TẠI** | `backend/src/astra_multi/orchestration/graph.py` (toàn file), `controller.py:1-60` | Hoàn toàn không có mã nào gọi `ChangeIssue` để chuyển trạng thái issue. `controller.py` thậm chí không import `ChangeIssue`. Mọi issue vĩnh viễn ở trạng thái `OPEN`. |
| **F-003** | High | VERIFIED | **TỒN TẠI** | `backend/src/astra_multi/orchestration/graph.py:212-215, 340, 346-347, 359-360` | - Dòng 212-215: `propose_node` tự lấy `approach[:100]` gán cho mọi requirements nếu rỗng.<br/>- Dòng 340, 346-347: `revise_node` tự gán `fallback_req_id = list(valid_reqs)[0]` khi step thiếu requirement IDs.<br/>- Dòng 359-360: Tự điền `deliverables=["Deliverable artifact"]` và `completion_criteria=["Completion criteria verified"]`. |
| **F-004** | High | VERIFIED | **TỒN TẠI** | `backend/src/astra_multi/orchestration/budget.py:124-150, 153-169, 170-177`<br/>`graph.py:80, 87` | - `reserve()` (dòng 124-150) ném lỗi khi đụng xung đột revision, không có vòng lặp retry `RevisionConflict`.<br/>- `settle()` (dòng 153-169) và `release()` (dòng 170-177) chỉ cập nhật in-memory, hoàn toàn không gọi `repository.commit()`.<br/>- `graph.py` chỉ lưu `self.budget_service` nhưng không node nào gọi. |
| **F-005** | Medium | VERIFIED | **TỒN TẠI** | `backend/src/astra_multi/orchestration/graph.py:218, 275-280` | - Dòng 218: `id=f"PROP-{uuid.uuid4().hex[:6]}"` sinh UUID ngẫu nhiên mỗi lần chạy node `propose`, phá vỡ tính idempotent khi resume/retry.<br/>- Dòng 275-280: `review_node` tăng counter khi ID đã có sẵn trong state, tạo ra issue trùng lặp khi chạy lại. |
| **F-006** | Medium | VERIFIED | **TỒN TẠI** | `backend/src/astra_multi/orchestration/graph.py:265` | `valid_reqs = {r.id for task in curr_state.tasks for r in task.requirements}` gom tất cả requirements của các task version cũ thay vì chỉ lấy phiên bản hiện tại `curr_state.task.requirements`. |
| **F-007** | Medium | VERIFIED | **TỒN TẠI** | `backend/src/astra_multi/orchestration/graph.py:365-388` | `revise_node` luôn sinh `DEC-{dec_counter}` mới và gọi `ctrl.record_decision(dec)`, không có cơ chế invalidate hoặc supersede decisions cũ từ các revision trước. |
| **F-008** | High | VERIFIED | **TỒN TẠI** | `backend/src/astra_multi/orchestration/graph.py:423-446` | `quality_gate_node` chỉ duyệt thủ công mảng problems, không hề import hoặc gọi `StructuralQualityValidator` từ `exports/quality_validator.py`. |

> **Kết luận đối soát:** Toàn bộ 8/8 Findings từ `BACKEND_AUDIT.md` đều **TỒN TẠI** trên mã nguồn hiện tại với vị trí dòng code khớp chính xác (sai lệch $\le 1$ dòng do định dạng).

---

## 3. Bản đồ Đồ thị Node và Cạnh hiện tại (`orchestration/graph.py`)

Đồ thị được định nghĩa trong hàm `create_workflow_graph()` tại `backend/src/astra_multi/orchestration/graph.py:487-521`.

### 3.1. Danh sách Nodes (11 nodes)
1. `intake`: Khởi tạo run, kiểm tra snapshot & requirements.
2. `snapshot`: Chuẩn bị snapshot repository.
3. `investigate`: Thu thập thông tin repo & ngữ cảnh kỹ thuật.
4. `planner_analysis`: Phân tích độc lập của Planner (cách ly ngữ cảnh).
5. `reviewer_analysis`: Phân tích độc lập của Reviewer (cách ly ngữ cảnh).
6. `propose`: Sinh Proposal kiến trúc ban đầu.
7. `review`: Reviewer đánh giá Proposal, nêu Issues.
8. `verify`: Thu thập Evidence kỹ thuật qua Sandbox / Tool.
9. `revise`: Synthesizer tổng hợp PlanRevision và Decisions.
10. `gate`: Quality Gate kiểm tra cấu trúc, blockers, coverage, stagnation.
11. `export`: Xuất kết quả terminal (hoàn tất run).

### 3.2. Sơ đồ Cạnh (Edge Topology dạng văn bản)

```text
[START]
   │
   ▼
intake
   │
   ▼
snapshot
   │
   ▼
investigate ────────┬────────────────────────┐
                    │ (nhánh song song)      │ (nhánh song song)
                    ▼                        ▼
             planner_analysis         reviewer_analysis
                    │                        │
                    └───────────┬────────────┘
                                │ (hội tụ)
                                ▼
                             propose
                                │
                                ▼
                             review ◄──────────────────────────────┐
                                │                                  │
                                ▼                                  │
                             verify                                │
                                │                                  │
                                ▼                                  │ (VÒNG LẶP HỎNG: F-001)
                             revise                                │ Trả về "review",
                                │                                  │ bỏ qua "propose"
                                ▼                                  │
                              gate ────────────────────────────────┘
                                │
                                │ (nếu gate_passed == True HOẶC hết rounds / đình trệ)
                                ▼
                              export
                                │
                                ▼
                              [END]
```

### 3.3. Chi tiết điều kiện của `should_loop_or_export`

Mã nguồn tại `graph.py:477-485`:
```python
def should_loop_or_export(state: OrchestrationState) -> str:
    if state.get("gate_passed"):
        return "export"
    round_num = state.get("round", 0)
    max_rounds = state.get("max_rounds", 2)
    if round_num >= max_rounds or detector.is_stagnant():
        return "export"
    return "review"
```

**Bảng quyết định định tuyến:**

| Điều kiện 1: `gate_passed` | Điều kiện 2: `round >= max_rounds` | Điều kiện 3: `is_stagnant()` | Kết quả trả về | Node tiếp theo | Ý nghĩa |
| :---: | :---: | :---: | :---: | :---: | :--- |
| `True` | Bất kỳ | Bất kỳ | `"export"` | `export` | Cổng thông qua, xuất kết quả |
| `False` | `True` | Bất kỳ | `"export"` | `export` | Đạt giới hạn số vòng, buộc xuất `PARTIAL` |
| `False` | Bất kỳ | `True` | `"export"` | `export` | Phát hiện đình trệ, buộc xuất `PARTIAL` |
| `False` | `False` | `False` | `"review"` | `review` | **LỖI (F-001):** Quay lại `review`, bỏ qua `propose` |

---

## 4. Kiểm chứng Invariant "Fenced lease" (`persistence/sqlite.py`)

Trong `BACKEND_AUDIT.md`, Invariant này được ghi nhận ở trạng thái **SUSPECTED** do chưa kiểm tra trực tiếp mã nguồn.

### Kết luận: **ENFORCED (Đã được thực thi đầy đủ và bảo vệ nghiêm ngặt)**

### Bằng chứng mã nguồn từ `backend/src/astra_multi/persistence/sqlite.py`:

1. **Khóa Epoch tăng đơn điệu và phát hiện xung đột (`acquire`, dòng 283-305):**
   ```python
   # sqlite.py:289-304
   row = self.connection.execute(
       "SELECT epoch, expires_at FROM leases WHERE run_id=?", (run_id,)
   ).fetchone()
   if row and datetime.fromisoformat(row[1]) > now:
       raise LeaseLost("run already leased")
   lease = Lease(
       run_id=run_id,
       owner=owner,
       token=str(uuid4()),
       epoch=row[0] + 1 if row else 1,
       expires_at=now + timedelta(seconds=ttl),
   )
   ```
   - Mỗi lần acquire lease thành công, `epoch` tăng đơn điệu (`epoch = row[0] + 1`).
   - Nếu lease đang còn hiệu lực (`expires_at > now`), hệ thống từ chối cấp và ném `LeaseLost`.

2. **Hàm kiểm tra Fenced Lease đa điều kiện (`_check_lease`, dòng 258-276):**
   ```python
   # sqlite.py:258-276
   def _check_lease(self, run_id: str, lease: Lease) -> Lease:
       row = self.connection.execute(
           "SELECT owner, token, epoch, expires_at FROM leases WHERE run_id=?",
           (run_id,),
       ).fetchone()
       if row is None:
           raise LeaseLost("run has no lease")
       current = Lease(
           run_id=run_id, owner=row[0], token=row[1], epoch=row[2], expires_at=row[3]
       )
       if (
           lease.run_id != run_id
           or current.token != lease.token
           or current.epoch != lease.epoch
           or current.owner != lease.owner
           or current.expires_at <= self.clock()
       ):
           raise LeaseLost("lease expired or ownership changed")
       return current
   ```
   - Kiểm tra nghiêm ngặt 5 yếu tố: `run_id`, `token`, `epoch`, `owner` và `expires_at > clock()`. Bất kỳ vi phạm nào đều ném `LeaseLost`.

3. **Hai lớp kiểm tra Fencing trong giao dịch Commit (`commit`, dòng 177-256):**
   ```python
   # sqlite.py:184-256
   with self._transaction(): # BEGIN IMMEDIATE dưới threading.Lock
       self._check_lease(run_id, lease) # LỚP 1: Kiểm tra trước khi mutate
       ...
       # Kiểm tra optimistic concurrency revision
       cursor = self.connection.execute(
           "UPDATE runs SET revision=?, state_json=? WHERE id=? AND revision=?",
           (updated.run.revision, updated.model_dump_json(), run_id, command.expected_revision),
       )
       if cursor.rowcount != 1:
           raise RevisionConflict("concurrent revision update")
       ...
       self._check_lease(run_id, lease) # LỚP 2: Kiểm tra lại trước khi return
       return operation
   ```
   - `_check_lease()` được gọi hai lần: trước khi thực hiện mutation và ngay trước khi commit hoàn tất.
   - Kết hợp với `BEGIN IMMEDIATE` và `RevisionConflict` bảo đảm không có race condition nào ghi đè dữ liệu khi lease bị mất hoặc quá hạn.

---

## 5. Đánh giá Độ bao phủ Test cho Vòng lặp $\ge 2$ vòng

### Kết quả rà soát:
1. **Trong `tests/test_workflow.py`:**
   - Lớp `TestBoundedLoop` có `test_respects_max_rounds` (dòng 77), nhưng test này chạy trên mock workflow prototype cũ (`astra_multi.workflow`) và kết thúc ngay ở round 1 (`round <= max_rounds`). Chưa từng chạy qua 2 vòng thực tế.

2. **Trong `tests/integration/test_orchestration_workflow.py`:**
   - Có **1 test duy nhất** chạy qua 2 vòng: `test_workflow_multi_round_decision_id_uniqueness()` (dòng 282-407).
   - Test này ép loop bằng cách để trống `REQ-002` ở call 1 của Synthesizer, khiến Gate ở round 1 fail do thiếu requirement coverage, sau đó vòng 2 bổ sung `REQ-002` để Gate pass.

### Lỗ hổng kiểm thử (Gaps):
Mặc dù test trên có chạy qua 2 vòng, nó **KHÔNG BẢO ĐẢM TÍNH ĐÚNG ĐẮN CỦA MULTI-AGENT LOOP THỰC TẾ**:
- **Không kiểm tra `propose` qua nhiều vòng:** Vì đồ thị bị lỗi F-001 (Gate quay về `review`), node `propose` chỉ chạy đúng 1 lần duy nhất trong toàn bộ test run. Không có assertion nào kiểm tra `propose` được gọi lại ở round 2.
- **Không có Issue nào được kiểm tra:** Test giả lập adapter trả về `issues: []` (danh sách rỗng). Do đó hoàn toàn không kiểm tra được luồng phát hiện issue ở round 1 và đóng issue ở round 2.
- **Không có test cho kịch bản Gate Fail do Blocker:** Chưa có test nào kiểm tra việc Gate fail do blocker issue kéo dài cho tới khi chạm `max_rounds` và xuất kết quả `PARTIAL` với đúng lý do dừng (`StopReason.MAX_ROUNDS_REACHED` hoặc `StopReason.UNRESOLVED_BLOCKERS`).

---

## 6. Tổng kết Baseline & Khuyến nghị trước Giai đoạn 1

1. **Baseline trạng thái:** Mã nguồn hiện tại hoàn toàn khớp với phát hiện của `BACKEND_AUDIT.md`. Invariant "Fenced lease" được xác nhận `ENFORCED`.
2. **Sự sẵn sàng:** Bộ test suite hiện tại chạy 100% pass (352/352 tests hợp lệ). Đây là tiền đề an toàn để tiến hành Giai đoạn 1.
3. **Kế hoạch TDD bắt buộc khi fix:**
   - Với **F-001**: Bắt buộc viết test mới yêu cầu `propose_node` được gọi ở mỗi round khi lặp (sẽ FAIL trên code hiện tại và PASS sau khi sửa `should_loop_or_export`).
   - Với **F-003**: Bắt buộc viết test mới kiểm tra Gate chặn các đề xuất thiếu coverage/deliverables rỗng (sẽ FAIL trên code hiện tại do spoofing và PASS khi gỡ spoofing).
   - Với **F-008**: Bắt buộc viết test mới kiểm tra Gate bắt lỗi cấu trúc DAG qua `StructuralQualityValidator`.
