# P6 — Đánh giá chất lượng và hoàn thiện độ tin cậy

Trạng thái: TODO. Ước lượng: 3–5 ngày công. Prerequisite: P5 đạt.

## 1. Mục tiêu

Xác minh sản phẩm vận hành đúng và multi-agent có lợi ích thực tế so với một model. Tham chiếu [PLAN.md](../PLAN.md), mục 12–14. Vùng code/tài liệu: `tests/recovery/`, `evaluations/`, `docs/`, các module cần sửa theo lỗi tái hiện được.

## 2. Tasks

### P6.1 — Fault injection và integration invariants

- **Phụ thuộc:** P5.5.
- **Thực hiện:** chạy matrix lỗi cross-component: kill trước/sau commit/checkpoint, expired lease, rate limit, invalid schema, budget race, missing sandbox, stale snapshot, cancel và SSE reconnect.
- **Contract:** dùng fault points và fixtures tái hiện được; mọi bug có ảnh hưởng phải được sửa tại module sở hữu và thêm regression test có ý nghĩa.
- **Đầu ra:** reliability report gồm scenario, expected, actual, artifact và remaining issues.
- **Nghiệm thu:** không mất committed artifact, không duplicate canonical revision; zero FINAL với blocker trong fixture tests; không vượt reservation cap; unavailable checks không biến thành PASS.
- **Kiểm chứng:** tận dụng test các phase trước, bổ sung seams chưa được kiểm tra; rerun test liên quan sau sửa, sau đó regression suite một lần.

### P6.2 — Evaluation harness và baseline công bằng

- **Phụ thuộc:** P6.1 cho độ ổn định; có thể chuẩn bị dataset sau P5.
- **Thực hiện:** ít nhất 12 nhiệm vụ gồm bug fix/feature/refactor/migration/ambiguous/greenfield; snapshot, constraints và acceptance cố định; baseline một model có cùng tools và tổng budget cap tương đương; rubric 0–4, anonymized outputs.
- **Contract:** lưu model/config/prompt versions, task ID, seed nếu provider hỗ trợ, repetition, usage/cost, latency và raw artifacts; lỗi/timeouts không bị loại âm thầm khỏi thống kê. Ba lần mỗi cấu hình nếu budget cho phép, ghi rõ actual sample count.
- **Đầu ra:** dataset manifest, baseline runner, multi-agent runner, scoring forms và report generator.
- **Nghiệm thu:** cùng input snapshot và rules giữa cấu hình; không dùng test set để tune rồi báo lại như đánh giá độc lập; cần tune thì tách development set và held-out set.
- **Kiểm chứng:** dry run fake providers để kiểm tra harness, sau đó chạy pilot thật theo budget được xác nhận.

### P6.3 — Pilot và thực thi mẫu kế hoạch

- **Phụ thuộc:** P6.2 và budget/reviewer sẵn sàng.
- **Thực hiện:** chấm ẩn cấu hình, ưu tiên con người; so sánh correctness/completeness/executability/evidence/proportionality, critical omission, re-plan, latency và cost; thực thi tối thiểu bốn kế hoạch đại diện trong môi trường thử nghiệm, giữ workload so sánh tương đương giữa cấu hình.
- **Contract:** định nghĩa critical omission/re-plan trước khi chấm; lưu sửa đổi phải thực hiện khi coding; tách lỗi model lập plan khỏi thay đổi yêu cầu ngoài dự kiến. Không để cùng LLM là nguồn chấm duy nhất.
- **Đầu ra:** pilot report với sample count, median/range, điểm trung bình, omission/re-plan rate, limitations và đề nghị tiếp tục/chỉnh sửa.
- **Nghiệm thu:** đạt ngưỡng đã chốt tại P0: chất lượng trung bình ít nhất bằng baseline, critical omission không tăng, có ít nhất một cải thiện đo được; đồng thời đạt reliability invariants và budget cap. Nếu không đạt, ghi pilot NOT_PASSED cùng backlog ưu tiên.
- **Kiểm chứng:** reproducible report từ raw results; audit mẫu scores và implementation evidence. Thiếu budget hoặc human review ghi BLOCKED, không suy ra chất lượng từ fake run.

### P6.4 — Handoff bản pilot

- **Phụ thuộc:** P6.1–P6.3 có kết quả rõ ràng.
- **Thực hiện:** setup từ môi trường sạch; hướng dẫn config/provider/sandbox, backup DB+artifacts, restore nhất quán, migrations, log redaction và troubleshooting; chốt supported platforms/known limitations.
- **Contract:** readiness ghi rõ READY_FOR_PILOT hoặc NOT_READY dựa trên gates; deployment chỉ trong phạm vi local MVP; version tag/build metadata gắn evaluation config. Không cần tự commit/tag nếu chưa được yêu cầu.
- **Đầu ra:** runbook, release checklist đã điền bằng kết quả thực tế, evaluation summary, prioritized backlog và status cuối.
- **Nghiệm thu:** người khác theo hướng dẫn chạy được demo; restore backup đọc được committed run/export; không còn blocker đối với mức readiness công bố. Pilot fail vẫn bàn giao report trung thực, không đánh dấu phase release thành công.
- **Kiểm chứng:** clean setup smoke và backup/restore scenario; đối chiếu từng gate với bằng chứng.

## 3. Exit gate

- [ ] Reliability matrix đạt và lỗi nghiêm trọng được xử lý.
- [ ] Benchmark có baseline công bằng và dữ liệu thật.
- [ ] Có đánh giá thực thi mẫu plans, không chỉ chấm văn bản.
- [ ] Ngưỡng pilot đạt; nếu chưa đạt, phase còn BLOCKED/IN_PROGRESS và có follow-up cụ thể.
- [ ] Runbook/setup/restore đã kiểm tra, readiness và limitations chính xác.

**Bàn giao cuối:** ứng dụng local, bằng chứng chất lượng, runbook và backlog ưu tiên theo kết quả đo. Cập nhật [IMPLEMENTATION_STATUS.md](../IMPLEMENTATION_STATUS.md).
