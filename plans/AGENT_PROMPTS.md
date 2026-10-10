# Bộ prompt cho agent sửa lỗi Backend Astra Multi

Cách dùng: chạy lần lượt trong thư mục gốc của repo (Claude Code hoặc Agent tool). Mỗi giai đoạn = 1 agent `general-purpose` riêng, chạy tuần tự, vì giai đoạn sau phụ thuộc giai đoạn trước. Agent Verifier chạy độc lập, không thấy quá trình làm của agent sửa.

Thứ tự: P0 (baseline) -> P1 -> P2 (cần ADR trước) -> P3 -> V (verify)

---

## Prompt dùng chung (dán đầu MỌI prompt bên dưới)

```
Bạn là dev backend senior làm việc trên dự án Astra Multi (LangGraph multi-agent).
Nguồn sự thật về lỗi: file BACKEND_AUDIT.md ở gốc repo. Đọc nó trước.

Quy tắc bắt buộc:
1. Số dòng trong audit có thể đã lệch. Luôn mở code thật, xác nhận lỗi còn tồn tại
   trước khi sửa. Nếu code khác với mô tả audit, DỪNG và báo cáo chênh lệch.
2. KHÔNG làm yếu invariant, KHÔNG sửa/xóa test để cho xanh, KHÔNG thêm logic
   "làm giả dữ liệu" để qua Gate. Test đang xanh 100% nhưng loop vẫn hỏng, nên
   test cũ chưa đủ: mỗi fix phải đi kèm test mới FAIL trước fix, PASS sau fix.
3. Chỉ sửa trong phạm vi giai đoạn được giao. Gặp vấn đề ngoài phạm vi thì ghi
   vào cuối báo cáo, không tự sửa.
4. Giữ schema extra=forbid, strict DAG, terminal immutability, expected_revision.
5. Mỗi thay đổi nhỏ, commit riêng theo từng Finding (message: "fix(F-00X): ...").
6. Kết thúc bằng báo cáo: Finding nào đã sửa, file:line mới, test đã thêm, kết
   quả chạy full test suite, và những gì chưa chắc chắn.
```

---

## P0 - Baseline (chạy trước, chỉ đọc + chạy test)

```
[Prompt dùng chung]

Nhiệm vụ: lập baseline, KHÔNG sửa code.
1. Chạy full test suite, ghi lại số pass/fail.
2. Với từng Finding F-001..F-008, mở code và ghi: còn tồn tại không, vị trí hiện tại.
3. Mở orchestration/graph.py và vẽ lại (dạng văn bản) đồ thị node + cạnh hiện có,
   gồm cả điều kiện của should_loop_or_export.
4. Mở repository/sqlite.py và kiểm tra trực tiếp invariant "Fenced lease"
   (audit đang để SUSPECTED). Kết luận ENFORCED hay VIOLATED kèm bằng chứng.
5. Tìm xem đã có test nào cover vòng lặp >= 2 vòng chưa.
Xuất kết quả ra BASELINE.md.
```

---

## P1 - Fix luồng đồ thị và bỏ spoofing (F-001, F-003, F-006, F-008)

```
[Prompt dùng chung]

Phạm vi: F-001, F-003, F-006, F-008 trong orchestration/graph.py.
Không đụng tới Issue resolution, budget, hay uuid (để giai đoạn sau).

Việc cần làm, theo thứ tự (mỗi việc: viết test fail trước -> sửa -> test pass):
1. F-003: xóa toàn bộ logic spoofing ở propose_node (gán 100 ký tự đầu của
   approach cho coverage) và revise_node (điền cứng deliverables/criteria).
   Nếu LLM bỏ sót, state phải giữ nguyên thiếu sót để Gate chặn.
   Test: output LLM thiếu coverage -> Gate từ chối, không có dữ liệu tự sinh.
2. F-008: quality_gate_node phải gọi StructuralQualityValidator
   (exports/quality_validator.py) ngoài các check thủ công hiện có.
   Test: plan có chu trình DAG -> Gate báo lỗi.
3. F-006: review_node dùng curr_state.task.requirements thay vì gộp từ
   curr_state.tasks. Test: requirement đã bị xóa ở version mới không nằm trong valid_reqs.
4. F-001: should_loop_or_export trả "propose" thay vì "review" khi cần lặp.
   Kiểm tra kỹ cả 2 chỗ (khoảng dòng 484 và 517) và mapping cạnh có điều kiện
   trong builder của graph.
   Test: chạy loop 2 vòng bằng LLM giả (fake), assert propose_node được gọi đúng 2 lần.

Tiêu chí xong: input thiếu sót bị chặn ở Gate, đồ thị quay đúng propose, full test xanh.
```

---

## P2 - Idempotency và Issue resolution (F-002, F-005, F-007)

> **Chặn bởi quyết định của con người.** Điền mục ADR bên dưới trước khi chạy. Nếu để trống, agent phải dừng sau bước 1.

```
[Prompt dùng chung]

Phạm vi: F-005, F-002, F-007.

QUYẾT ĐỊNH ADR (người dùng điền, chọn 1):
  [ ] A: thêm pha SEMANTIC_REVIEW giữa REVISE và QUALITY_GATE
  [ ] B: REVISE -> REVIEW lại plan mới, chỉ khi reviewer PASS hết mới sang GATE
Nếu cả hai đều chưa tick: viết docs/adr/00X-reviewer-independent-pass.md liệt kê
tác động của A và B lên PHASE_TRANSITIONS (domain/policies.py:58), invariant
"thứ tự 10 pha", và test hiện có, rồi DỪNG, không sửa code.

Nếu đã có quyết định:
1. F-005: thay uuid.uuid4() trong node bằng ID dẫn xuất tất định từ
   (run_id, round, node_name, index) (uuid5 hoặc content hash).
   Test: invoke graph 2 lần với cùng input/resume -> không nhân bản Proposal/Issue.
2. F-002: thêm mảng `resolutions` vào ReviewOutput (roles.py). review_node lặp
   qua resolutions và commit ChangeIssue qua repository.commit, tuân thủ
   ISSUE_TRANSITIONS (policies.py:71) và điều kiện reviewer độc lập PASS
   (policies.py:116-129), dùng expected_revision đúng. Reviewer phải đánh giá trên
   revision plan MỚI NHẤT theo phương án ADR đã chọn.
   Test: issue blocking được đóng thành RESOLVED bởi reviewer độc lập; reviewer
   không độc lập thì bị từ chối.
3. F-007: revise_node không được chỉ thêm Decision mới. Thêm cơ chế supersede
   (hoặc chỉ giữ decision hợp lệ với revision hiện tại). Đây là thay đổi domain
   model: nếu cần đổi schema, liệt kê tác động trước khi làm.
   Test: sau N vòng, số Decision active không phình theo N.

Tiêu chí xong: run Minesweeper (RUN-c5039d07 hoặc fixture tương đương, LLM giả)
đạt FINAL thay vì PARTIAL, và FINAL vẫn chỉ phát hành bởi P4.
```

---

## P3 - Budget bền vững (F-004 + tối ưu O(N))

```
[Prompt dùng chung]

Phạm vi: orchestration/budget.py và các điểm gọi trong graph.py (F-004).

1. reserve/settle/release: bọc repository.commit trong vòng lặp có giới hạn
   (tối đa N lần, có backoff) bắt RevisionConflict, đọc lại state mới mỗi lần thử.
   Hết số lần thì ném lỗi rõ ràng, không treo vô hạn.
2. settle và release hiện chỉ đổi bộ đếm in-memory: phải persist qua
   repository.commit để sống sót qua restart.
3. graph.py: gọi reserve() trước mỗi lần gọi model, settle() khi thành công,
   release() khi lỗi (dùng try/finally để không rò reservation).
4. Tối ưu: thay vòng lặp O(N) trên self._reservations bằng 2 bộ đếm
   _reserved_tokens/_reserved_cost cập nhật tại chỗ. Thêm test kiểm tra bộ đếm
   luôn khớp tổng tính lại từ đầu.

Test bắt buộc:
- 10 thread reserve đồng thời đều thành công, tổng không vượt ngân sách.
- Tạo service mới từ cùng DB sau "restart": cost/token không bị reset.
- Lỗi model -> release được gọi, reservation không bị rò.

Không đổi hành vi hạn mức ngân sách ngoài những gì trên.
```

---

## V - Verifier độc lập (chạy sau cùng, agent mới, không xem lịch sử các agent trước)

```
Bạn là reviewer độc lập. Không sửa code, chỉ kiểm tra và báo cáo.
Đọc BACKEND_AUDIT.md và `git log` / `git diff` từ commit trước P1.
Với từng Finding F-001..F-008:
 - Chạy lại bằng chứng gốc, xác nhận lỗi không còn tái hiện.
 - Xác nhận có test mới, và test đó thực sự fail khi revert fix
   (git stash phần sửa trong graph.py/budget.py rồi chạy lại test).
Kiểm tra thêm:
 - Không có test nào bị xóa/làm yếu, không có skip/xfail mới.
 - Không còn uuid4 trong graph nodes, không còn logic tự điền dữ liệu.
 - Chạy full suite + một run Minesweeper bằng LLM giả, xác nhận FINAL và 2 vòng gọi propose 2 lần.
Xuất VERIFY.md: bảng Finding -> PASS/FAIL + bằng chứng, và rủi ro còn lại.
```

---

## Ghi chú

- Thứ tự Effort theo audit: F-001/003/005/006/008 là S, F-004/007 là M, F-002 là L. P2 là giai đoạn rủi ro nhất.
- Race condition thực tế trong SQLite chưa được audit; P0 bước 4 sẽ làm rõ.
- Mục "Prompt bloat" trong audit (mục 6) chưa nằm trong giai đoạn nào, nên làm sau khi P1-P3 đã ổn định.
