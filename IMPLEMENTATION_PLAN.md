# Astra Multi — Kế hoạch triển khai cho dev agent

Ngày: 01/10/2026. Nguồn kiến trúc: [PLAN.md](PLAN.md), phiên bản 0.1.

## 1. Cách sử dụng

1. Đọc tài liệu này và [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md).
2. Mở plan của giai đoạn đang làm, đọc các mục PLAN.md được tham chiếu.
3. Nhận một task ID có đủ điều kiện bắt đầu; khảo sát code thực tế trước khi sửa.
4. Triển khai, chạy kiểm chứng, ghi bằng chứng và cập nhật trạng thái task.
5. Chỉ chuyển giai đoạn khi exit gate đã đạt; thiếu API key hoặc hạ tầng thì ghi BLOCKED, không tính kiểm tra giả lập là kiểm tra live.

PLAN.md là nguồn chuẩn kiến trúc. Các file dưới đây chi tiết hóa cùng roadmap P0–P6; không dùng song song hệ ID milestone A–D từng được đề xuất trong hội thoại.

## 2. Các giai đoạn

| Phase | Plan chi tiết | Đầu vào | Đầu ra chính | Ước lượng |
|---|---|---|---|---|
| P0 | [Khóa yêu cầu và thử nghiệm](plans/P0_DISCOVERY_AND_SPIKE.md) | PLAN.md | Workflow thử nghiệm runnable; ADR chọn runtime | 2–3 ngày |
| P1 | [Domain và persistence](plans/P1_DOMAIN_AND_PERSISTENCE.md) | P0 đạt | Contracts và storage có revision/idempotency | 3–4 ngày |
| P2 | [Snapshot, evidence và tools](plans/P2_SNAPSHOT_AND_TOOLS.md) | P1 đạt | Repo snapshot và công cụ kiểm chứng truy vết được | 3–5 ngày |
| P3 | [Model gateway và workflow](plans/P3_MODELS_AND_WORKFLOW.md) | P1; tích hợp P2 | Luồng CLI thực tế có giới hạn và resume | 4–6 ngày |
| P4 | [Quality gates và export](plans/P4_QUALITY_AND_EXPORT.md) | P3 đạt | Plan được kiểm tra, JSON/Markdown nhất quán | 2–3 ngày |
| P5 | [API và UI](plans/P5_API_AND_UI.md) | P4 đạt | Ứng dụng local dùng được end-to-end | 4–6 ngày |
| P6 | [Evaluation và hardening](plans/P6_EVALUATION_AND_HARDENING.md) | P5 đạt | Kết quả pilot, recovery và hướng dẫn vận hành | 3–5 ngày |

Tổng định hướng: 21–32 ngày công, cần hiệu chỉnh sau P0. Task con nằm trong thời lượng phase, không cộng thêm lần nữa.

```text
P0 → P1 → P2 ──────────┐
       └→ P3.1–P3.2 ──┴→ P3.3–P3.5 → P4 → P5 → P6
```

P2 và phần model gateway P3 có thể phát triển độc lập sau khi contracts P1 được chốt. Mặc định một dev agent thực hiện tuần tự; bảng dependency không phải yêu cầu tự tạo thêm agent.

## 3. Quy tắc chia việc và hoàn thành

- Task ID có dạng P0.1, P0.2…; task có một mục tiêu nghiệm thu chính.
- Trong mỗi plan, “Vùng code” chỉ là vị trí dự kiến. Agent phải dùng cấu trúc thực tế nếu đã tồn tại, không tạo bản triển khai trùng.
- Trạng thái task: TODO → IN_PROGRESS → DONE; BLOCKED khi thiếu prerequisite. Mỗi agent chỉ có một task IN_PROGRESS.
- Tự quyết chi tiết cục bộ có thể đảo ngược; ghi ADR hoặc hỏi khi thay đổi public contract, phạm vi hay lựa chọn kiến trúc.
- DONE yêu cầu có artifact và bằng chứng kiểm tra acceptance criteria. Test chưa chạy ghi NOT_RUN cùng lý do.
- Ghi command thật và kết quả vào status. Các mục “kiểm chứng” trong plan mô tả hành vi cần kiểm tra, chưa phải command đã tồn tại.
- Unit/integration test dùng fake providers có kết quả xác định; live smoke test tách riêng và chỉ chạy với cấu hình/budget có sẵn.
- Các giai đoạn sau tái sử dụng contract và artifact trước đó. Code spike chỉ được đưa vào sản phẩm sau khi đánh giá và refactor phần cần thiết.

## 4. Hợp đồng bàn giao giữa các phase

| Từ → đến | Hợp đồng cần bàn giao |
|---|---|
| P0 → P1 | Python/dependency versions, runtime decision, model adapter shape, lỗi hoặc giới hạn đã phát hiện |
| P1 → P2/P3 | Typed schemas, repository interfaces, operation ID, revision rules, event envelope |
| P2 → P3 | SnapshotRef, EvidenceRef, tool request/result, sandbox availability và context bundle |
| P3 → P4 | Candidate revision, issue resolution history, semantic review interface, stop reasons, usage |
| P4 → P5 | QualityReport, canonical export, application service commands/queries |
| P5 → P6 | OpenAPI, SSE contract, UI flow, runtime config và reproducible run artifacts |

## 5. Ma trận bao phủ yêu cầu chính

| Yêu cầu từ PLAN.md | Triển khai chính | Kiểm chứng tích hợp |
|---|---|---|
| REQ-01 — TaskSpec | P1.1, P3.3 | P4.1, P5.3 |
| REQ-02 — Cùng dữ kiện | P2.1–P2.3 | P3.3, P6.1 |
| REQ-03 — Phân tích độc lập | P0.2, P3.2–P3.3 | P3.5, P6.1 |
| REQ-04 — Issue cụ thể | P1.1, P3.3 | P4.2 |
| REQ-05 — Giải quyết có căn cứ | P1.2, P3.3 | P4.2, P6.1 |
| REQ-06 — Plan thực thi được | P4.1–P4.2 | P6.2–P6.3 |
| REQ-07 — Truy vết | P1.1, P2.3, P4.1 | P5.4, P6.1 |
| REQ-08 — Recovery | P0.3, P1.3–P1.4, P3.5 | P6.1 |
| REQ-09 — Giới hạn | P3.1, P3.4 | P6.1 |
| REQ-10 — Nhiều model | P0.4, P3.1 | P3.5, P6.2 |
| REQ-11 — Partial trung thực | P3.4, P4.2 | P5.5, P6.1 |
| REQ-12 — Export nhất quán | P4.3 | P4.4, P5.5 |

## 6. Prompt giao task cho dev agent

```text
Workspace: D:\Astra multi
Task được giao: [P0.1 hoặc task ID cụ thể]
Plan giai đoạn: [đường dẫn file trong plans/]

Đọc IMPLEMENTATION_PLAN.md, IMPLEMENTATION_STATUS.md và phần PLAN.md
được plan giai đoạn tham chiếu. Kiểm tra prerequisite và code thực tế.

Hoàn thành task được giao theo mục tiêu, contracts, đầu ra và acceptance
criteria trong plan. Chạy kiểm chứng phù hợp, sửa lỗi trong phạm vi task.
Ghi rõ kiểm tra nào đã chạy, kết quả nào chưa xác minh.

Cập nhật IMPLEMENTATION_STATUS.md với thay đổi, command thực tế, kết quả,
blocker, contract mới và task tiếp theo. Nếu prerequisite thiếu, ghi BLOCKED
và mô tả chính xác điều cần bổ sung. Chỉ đánh dấu DONE khi có bằng chứng.

Báo cáo cuối: mục tiêu đạt được, file chính, kết quả kiểm chứng,
acceptance criteria chưa đạt và hướng bàn giao.
```

**Task bắt đầu: P0.1.** Sau khi xác nhận các giả định cần thiết, làm P0.2 để có workflow giả lập chạy xuyên suốt trước khi mở rộng sản phẩm.
