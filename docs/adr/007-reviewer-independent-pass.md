# ADR-007: Reviewer Independent Pass & Blocking Issue Resolution Architecture

**Trạng thái:** ACCEPTED / ĐÃ CHẤP THUẬN (Phương án A)  
**Ngày lập:** 2026-10-07  
**Ngữ cảnh:** BACKEND_AUDIT.md Finding F-002, Invariant "FINAL chỉ do P4" ([domain/policies.py:298](file:///d:/Astra%20multi/backend/src/astra_multi/domain/policies.py#L298)), và Invariant "Điều kiện Reviewer độc lập PASS" ([domain/policies.py:116-129](file:///d:/Astra%20multi/backend/src/astra_multi/domain/policies.py#L116-L129)).

---

## 1. Vấn đề Kiến trúc cốt lõi (Problem Statement)

Hệ thống Astra Multi thiết kế với cam kết kiểm chứng chất lượng ở mức cao nhất: một bản kế hoạch kiến trúc chỉ được cấp trạng thái `FINAL` khi:
1. `StructuralQualityValidator` (P4.1) đạt `passed = True` (0 vi phạm blocker).
2. Toàn bộ các vấn đề nghiêm trọng (`IssueSeverity.BLOCKING`) đều đã được giải quyết (`status == IssueStatus.RESOLVED`).
3. Theo chính sách [domain/policies.py:116-129](file:///d:/Astra%20multi/backend/src/astra_multi/domain/policies.py#L116-L129), một blocking issue chỉ được phép chuyển sang `RESOLVED` khi có một tác nhân **Reviewer độc lập (P4)** đánh giá `PASS` trên **chính bản Plan Revision mới hơn** (`reviewed_revision == state.plan.revision > issue.based_on_revision`).

### Điểm nghẽn trong luồng hiện tại:
- Luồng đồ thị ban đầu: `PROPOSE → REVIEW → VERIFY → REVISE → QUALITY_GATE`.
- Tại pha `REVISE`, Synthesizer sinh ra bản kế hoạch sửa đổi mới (`PlanRevision` revision $N$).
- Tuy nhiên, ngay sau đó luồng chuyển thẳng sang `QUALITY_GATE`.
- Tại `QUALITY_GATE`, vì chưa hề có bất kỳ lượt đánh giá nào của Reviewer độc lập trên bản Revision $N$ vừa sinh ra, mọi blocking issue vẫn giữ nguyên trạng thái `OPEN`.
- **Hậu quả:** Quality Gate luôn luôn từ chối (`gate_passed = False`). Khi chạm giới hạn số vòng (`max_rounds`), run Minesweeper (`RUN-c5039d07`) bị buộc dừng ở trạng thái `PARTIAL`, không bao giờ hội tụ được sang `FINAL`.

---

## 2. So sánh Toàn diện Hai Phương án Quyết định (Option A vs Option B)

---

### PHƯƠNG ÁN A: Thêm pha `SEMANTIC_REVIEW` giữa `REVISE` và `QUALITY_GATE` (ĐÃ CHẤP THUẬN)

#### 2.1. Luồng đề xuất:
```text
PROPOSE → REVIEW → VERIFY → REVISE → SEMANTIC_REVIEW → QUALITY_GATE ──┬──► EXPORT (FINAL, nếu đạt)
                                                                       │
                                                                       └──► PROPOSE (nếu fail & còn round)
```

#### 2.2. Chi tiết thực thi:
1. Thêm giá trị `SEMANTIC_REVIEW = "SEMANTIC_REVIEW"` vào `RunPhase` enum trong `domain/models.py`.
2. Bổ sung `semantic_review_node` vào `orchestration/graph.py` giữa `revise` và `gate`.
3. Tác nhân Reviewer độc lập (P4) trong node này nhận context gồm `TaskSpec`, bản `PlanRevision` mới nhất từ `REVISE`, và danh sách issue mở.
4. Reviewer đánh giá và trả về `resolutions: list[IssueResolution]`.
5. Controller thực hiện lệnh `ChangeIssue` hợp lệ theo `ISSUE_TRANSITIONS` để chuyển các issue đạt yêu cầu thành `RESOLVED`.
6. Luồng chuyển sang `QUALITY_GATE`.

#### 2.3. Tác động lên `PHASE_TRANSITIONS` (`domain/policies.py:58`):
- **Cập nhật bảng chuyển pha**:
  ```python
  RunPhase.REVISE: frozenset({RunPhase.QUALITY_GATE, RunPhase.SEMANTIC_REVIEW}),
  RunPhase.SEMANTIC_REVIEW: frozenset({RunPhase.QUALITY_GATE}),
  RunPhase.QUALITY_GATE: frozenset({RunPhase.REVIEW, RunPhase.EXPORT, RunPhase.PROPOSE}),
  ```
- Không làm vỡ logic state machine, chỉ nối dài thêm 1 mắt xích xác định.

#### 2.4. Tác động lên Invariant "Thứ tự 10 pha":
- **NÂNG CẤP INVARIANT "Thứ tự 10 pha" $\rightarrow$ "Thứ tự 11 pha"**:
  - Quy trình chính thức chuyển từ **10 pha** thành **11 pha**:
    `INTAKE → SNAPSHOT → INVESTIGATE → INDEPENDENT_ANALYSIS → PROPOSE → REVIEW → VERIFY → REVISE → SEMANTIC_REVIEW → QUALITY_GATE → EXPORT`.
  - Cần cập nhật lại định nghĩa 10 pha trong [ADR-003:17](file:///d:/Astra%20multi/docs/adr/ADR-003-discussion-protocol.md#L17) và bảng Invariants trong [BACKEND_AUDIT.md](file:///d:/Astra%20multi/docs/audit/BACKEND_AUDIT.md).

#### 2.5. Tác động lên Test Suite hiện có:
- `tests/unit/test_domain.py`: `test_phase_transition_table` kiểm tra ma trận tất cả các cặp `(source, target)`. Khi thêm enum `RunPhase.SEMANTIC_REVIEW`, test sẽ tự động kiểm tra thêm dòng/cột của pha này theo `PHASE_TRANSITIONS`.
- `tests/integration/test_orchestration_workflow.py`: Cần cập nhật `test_workflow_happy_path` vì luồng event sẽ có thêm sự kiện `[SEMANTIC_REVIEW]`.
- Tests kiểm tra checkpoint / crash recovery: Cần hỗ trợ khôi phục trạng thái tại pha mới.

#### 2.6. Ưu & Nhược điểm:
- **Ưu điểm:**
  - **Tách biệt ngữ cảnh tuyệt đối (Context Isolation & Single Responsibility):** Node `review` ban đầu tập trung phân tích lỗ hổng trên Proposal; Node `semantic_review` tập trung nghiệm thu Plan Revision. Prompt của 2 node không bị chồng chéo hay quá tải.
  - **Đồ thị tuyến tính & An toàn (Single Gate Control):** Mọi quyết định rẽ nhánh lặp đều tập trung tại duy nhất `QUALITY_GATE`, loại bỏ hoàn toàn rủi ro vòng lặp vô tận (infinite loop).
- **Nhược điểm:**
  - Đổi enum domain model (`RunPhase`), yêu cầu cập nhật định nghĩa 10 pha thành 11 pha.
  - Thêm 1 lần gọi LLM (tăng chi phí token và thời gian chạy cho mỗi round).

---

### PHƯƠNG ÁN B: `REVISE → REVIEW` lại plan mới, chỉ khi reviewer PASS hết mới sang GATE

#### 2.2. Luồng đề xuất:
```text
PROPOSE → REVIEW (lần 1) → VERIFY → REVISE → REVIEW (lần 2: re-review plan mới)
                                                     │
                                       ┌─────────────┴─────────────┐
                         (nếu reviewer PASS hết)       (nếu còn blockers)
                                       │                           │
                                       ▼                           ▼
                                  QUALITY_GATE                  PROPOSE
                                       │
                                       ▼
                              EXPORT (FINAL/PARTIAL)
```

#### 2.2. Chi tiết thực thi:
1. Giữ nguyên 10 enum values của `RunPhase`.
2. Thay đổi định tuyến đồ thị LangGraph: `revise` nối cạnh sang `review`.
3. Node `review_node` được nâng cấp để hỗ trợ 2 chế độ (dual-mode):
   - Chế độ 1 (sau Propose): Phát hiện issue mới trên Proposal ban đầu.
   - Chế độ 2 (sau Revise): Đánh giá Plan Revision mới và phát lệnh `ChangeIssue` để đóng issue.
4. Rẽ nhánh: Nếu Reviewer pass hết blocker $\rightarrow$ chuyển sang `QUALITY_GATE`; nếu còn blocker $\rightarrow$ quay lại `PROPOSE`.

#### 2.3. Tác động lên `PHASE_TRANSITIONS` (`domain/policies.py:58`):
- **BẮT BUỘC PHẢI THAY ĐỔI BẢNG `PHASE_TRANSITIONS`**:
  - Hiện tại, `PHASE_TRANSITIONS` quy định:
    ```python
    RunPhase.REVISE: frozenset({RunPhase.QUALITY_GATE}),
    RunPhase.REVIEW: frozenset({RunPhase.VERIFY, RunPhase.REVISE}),
    ```
  - Nếu đi theo Phương án B, các bước chuyển pha sau sẽ ném lỗi `InvalidState: invalid phase transition` nếu không sửa chính sách:
    - `REVISE → REVIEW`: Vi phạm `PHASE_TRANSITIONS[RunPhase.REVISE]`
    - `REVIEW → QUALITY_GATE`: Vi phạm `PHASE_TRANSITIONS[RunPhase.REVIEW]`
    - `REVIEW → PROPOSE`: Vi phạm `PHASE_TRANSITIONS[RunPhase.REVIEW]`
  - Do đó, bắt buộc phải nới lỏng chính sách chuyển pha thành:
    ```python
    RunPhase.REVISE: frozenset({RunPhase.REVIEW, RunPhase.QUALITY_GATE}),
    RunPhase.REVIEW: frozenset({RunPhase.VERIFY, RunPhase.REVISE, RunPhase.QUALITY_GATE, RunPhase.PROPOSE}),
    ```

#### 2.4. Tác động lên Invariant "Thứ tự 10 pha":
- **GIỮ NGUYÊN 10 TÊN PHA**, NHƯNG **PHÁ VỠ TÍNH TUYẾN TÍNH THỨ TỰ PHA**:
  - Pha `REVIEW` xuất hiện 2 lần trong cùng một vòng đời thực thi (`... → PROPOSE → REVIEW → VERIFY → REVISE → REVIEW → ...`).
  - Giao thức thảo luận không còn là chuỗi pha tuần tự cố định $1 \rightarrow 10$ mà trở thành đồ thị có chu trình lặp con (nested cycle).

#### 2.5. Tác động lên Test Suite hiện có:
- `test_workflow_happy_path`: Sẽ fail vì đồ thị không còn đi thẳng từ `REVISE → QUALITY_GATE`.
- `test_workflow_multi_round_decision_id_uniqueness`: Bị ảnh hưởng bởi thứ tự duyệt node mới.
- **RỦI RO LỚN VỀ INFINITE LOOP TRONG TEST**:
  - Nếu từ `REVIEW` rẽ nhánh trực tiếp về `PROPOSE` khi còn blocker, luồng đã **bỏ qua hoàn toàn `QUALITY_GATE`**.
  - Trong khi đó, chốt chặn `max_rounds` và `StagnationDetector` hiện nằm tại `QUALITY_GATE`.
  - Nếu test gặp trường hợp Reviewer không pass blocker, hệ thống sẽ rơi vào vòng lặp vô tận `PROPOSE → REVIEW → ... → REVIEW → PROPOSE` mà không bao giờ dừng để xuất `PARTIAL`!
  - Để khắc phục, biến thể an toàn của B bắt buộc phải luôn đi qua `QUALITY_GATE`:
    `REVISE → REVIEW (re-review) → QUALITY_GATE → (nếu fail: loop về PROPOSE)`.

#### 2.6. Ưu & Nhược điểm:
- **Ưu điểm:**
  - Không thêm enum mới vào `domain/models.py`.
- **Nhược điểm:**
  - **Quá tải vai trò tác tử (Role & Prompt Overload):** Một node `review_node` duy nhất phải gánh cả logic review khởi tạo lẫn logic nghiệm thu sửa đổi, dễ gây hallucination hoặc Reviewer quên đóng issue cũ.
  - **Phân tán quyền điều phối (Split-brain Routing):** Rẽ nhánh ở cả `REVIEW` và `GATE` làm đồ thị phức tạp, khó kiểm soát số vòng lặp.

---

## 3. Bảng Ma trận So sánh Kỹ thuật (Technical Matrix)

| Tiêu chí So sánh | Phương án A (Thêm `SEMANTIC_REVIEW`) | Phương án B (`REVISE → REVIEW` lại plan) |
| :--- | :--- | :--- |
| **Số lượng Enum `RunPhase`** | Tăng lên 11 (thêm `SEMANTIC_REVIEW`) | Giữ nguyên 10 enum values |
| **Bảng `PHASE_TRANSITIONS`** | Thêm chuyển pha tuyến tính rõ ràng | Bắt buộc nới lỏng nhiều chuyển pha chéo (`REVISE→REVIEW`, `REVIEW→GATE`, `REVIEW→PROPOSE`) |
| **Invariant "Thứ tự 10 pha"** | Nâng cấp thành **11 pha chuẩn hóa** | Giữ 10 tên pha nhưng lặp lại pha `REVIEW` 2 lần |
| **Độ rõ ràng của Prompt LLM** | **Cao**: Prompt nghiệm thu tách bạch chuyên trách | **Thấp**: Gộp 2 nhiệm vụ trái ngược vào 1 prompt |
| **Kiểm soát Bounded Loop** | **Tuyệt đối an toàn**: Quality Gate là cửa ngõ duy nhất | **Nguy cơ Infinite Loop** nếu rẽ nhánh từ Review bỏ qua Gate |
| **Sự ảnh hưởng tới Test Suite** | Nhẹ (cập nhật ma trận phase và event name) | Trung bình - Nặng (thay đổi toàn bộ routing và test lặp) |

---

## 4. Khuyến nghị Kiến trúc (Architectural Recommendation)

Kiến trúc sư Backend đề xuất:
1. **Lựa chọn tối ưu: Phương án A (SEMANTIC_REVIEW)** vì tính trong sáng về mặt thiết kế (Clean Architecture), tách biệt ranh giới trách nhiệm giữa phát hiện lỗi (Review ban đầu) và nghiệm thu kết quả sửa đổi (Semantic Review P4.2), bảo toàn nguyên tắc "Cổng kiểm soát đơn nhất" (Single Control Gate).
2. **Nếu chọn Phương án B:** Bắt buộc áp dụng biến thể **Single-Gate Control** (tức là sau `REVISE → REVIEW`, luồng BẮT BUỘC phải đi vào `QUALITY_GATE`, và Gate mới là nơi duy nhất quyết định quay về `PROPOSE` khi còn blocker hoặc hết rounds). Tuyệt đối không để node `REVIEW` rẽ nhánh trực tiếp về `PROPOSE` bỏ qua Gate.

---

**Quyết định cuối cùng:** [x] **Phương án A đã được chấp thuận và tích hợp vào hệ thống.**
