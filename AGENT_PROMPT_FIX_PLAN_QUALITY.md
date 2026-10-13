# Prompt cho agent code: sửa chất lượng plan của Astra Multi

Dán nguyên văn phần trong khối dưới đây cho agent (Claude Code / Cursor).
Làm theo thứ tự. Mỗi mục là một commit riêng. Dừng và báo cáo sau Phase 1 trước khi sang Phase 2.

```text
Bối cảnh: codebase Astra Multi (backend/src/astra_multi). Bài test 7 (thiết kế engine đa agent
Planner/Worker/Reviewer, review/revise, giới hạn vòng + token, resume, audit log) cho ra plan
đạt FINAL dù còn 4 issue open, hiểu sai REQ-003 (khôi phục khi lỗi), và thiếu sơ đồ/schema/
resume/chế độ lỗi. Nguyên nhân nằm ở luồng, không phải model. Hãy sửa các mục dưới đây.

QUY TẮC CHUNG
- Với mỗi mục: viết test fail trước, rồi sửa, rồi chạy full suite.
- Không xoá hoặc làm yếu test cũ, không thêm skip/xfail.
- Test mới phải thực sự fail khi revert phần sửa (kiểm tra bằng git stash phần sửa).
- Không thêm logic tự điền dữ liệu, không sinh ID giả, không uuid4 trong graph nodes.
- Trước khi sửa schema/store, đọc cách store lưu RunState và migration hiện có; không phá
  run cũ đã lưu.
- Tiếng Việt cho thông báo lỗi và stop_reason, giữ nguyên tên rule/ID bằng tiếng Anh.

===== PHASE 1: cổng chất lượng phải nói thật =====

[A] Finalize không được hardcode passed=True
- Hiện api/app.py (finalize_run, ~dòng 783-796) và cli.py (~295-313) tự tạo
  SemanticReviewAssessment(passed=True, ...). Đây là lý do plan ghi
  "satisfied all ... semantic review rubrics" dù chưa ai chấm.
- Sửa: semantic_review_node (orchestration/graph.py) phải ghi kết quả vào RunState/store:
  reviewed_plan_revision, passed, concerns, feedback.
  passed = true khi và chỉ khi: không còn issue mở mức warning trở lên, và (sau Phase 2)
  mọi RequirementVerdict là PASS.
- finalize_run (API + CLI) đọc kết quả đã lưu. Không có kết quả -> PARTIAL với lý do
  "Semantic review assessment not provided". Kết quả cũ (revision lệch) -> PARTIAL.
- Test: (1) finalize khi chưa có semantic review -> PARTIAL; (2) revision lệch -> PARTIAL;
  (3) còn issue warning mở -> PARTIAL; (4) đủ điều kiện -> FINAL.

[B] RULE-ISSUE-002 (quality_validator.py)
- Blocker nếu tồn tại issue severity in {BLOCKING, WARNING} với status in
  {OPEN, INVESTIGATING, PROPOSED_RESOLUTION}. Issue INFO không chặn nhưng phải được
  liệt kê trong mục 5 của export.
- remediation: "Giải quyết, từ chối hoặc đánh dấu trùng (DUPLICATE) mọi issue warning trở lên".
- Chú ý quality_gate_node dùng chung validator: khi hết max_rounds mà vẫn còn issue mở,
  run phải kết thúc PARTIAL với stop_reason nêu số issue còn lại, không crash.
- Test: plan có 1 warning open -> report.passed == False; sau khi resolve -> True.

[C] Bỏ các validator tự điền dữ liệu trong agents/roles.py
- StepDraft.normalize_requirement_ids tự điền ["REQ-001"], normalize_deliverables tự điền
  "Deliverable artifact", normalize_completion_criteria tự điền "Completion verified".
  Chúng làm RULE-COV-001, RULE-STEP-001, RULE-STEP-002 qua được với dữ liệu rỗng.
- SynthesizerOutput.normalize_issues_addressed bịa ra "ISSUE-{idx+1}" khi không parse được.
- Sửa: chỉ giữ chuẩn hoá hợp lệ (strip khoảng trắng, ép str -> list[str], trích ISSUE-xxx
  bằng regex). Giá trị rỗng hoặc không parse được thì raise ValidationError, KHÔNG điền thay.
  Kiểm tra cơ chế retry/repair khi LLM trả sai schema hiện có là gì và đảm bảo nó có giới hạn
  số lần; hết lượt thì run kết thúc PARTIAL với stop_reason rõ ràng.
- Test: step không có requirement_ids -> ValidationError; issues_addressed chứa chuỗi
  không có ID -> ValidationError; không còn chuỗi "Deliverable artifact"/"Completion verified"
  trong code (grep).

Sau Phase 1: chạy lại test 7 với cùng input. KỲ VỌNG: run kết thúc PARTIAL (vì còn issue
warning mở), không còn FINAL. Báo cáo trạng thái, stop_reason, danh sách issue còn mở.
Dừng ở đây và đưa kết quả cho tôi.

===== PHASE 2: để plan chứa được "thiết kế" =====

[D] Intake nhận ràng buộc, đầu ra mong muốn và acceptance thật
- CreateRunRequest (api/schemas.py) và cmd_create (cli.py) thêm:
  constraints: list[str] = [], non_goals: list[str] = [],
  expected_outputs: list[str] = [].
  requirements chấp nhận cả str lẫn {text, acceptance}.
- constraints/non_goals -> TaskSpec.constraints/non_goals. Mỗi expected_output -> một
  Requirement mới (REQ nối tiếp), để RULE-COV-001 bắt buộc phủ.
- Bỏ acceptance hardcode "Verified by design and candidate test steps". Nếu caller không
  cung cấp, dùng: "Plan nêu cơ chế cụ thể đáp ứng yêu cầu này và cách kiểm chứng: <req.text>".
- Test: tạo run với 2 requirements + 3 expected_outputs -> TaskSpec có 5 requirements;
  plan thiếu phủ expected_output thứ 3 -> RULE-COV-001 fail.

[E] Design artifacts + mode "design"
- agents/roles.py: thêm
    class DesignArtifactDraft(AgentContract):
        kind: Literal["state_machine","message_schema","stop_conditions",
                      "recovery_protocol","failure_modes","sequence_flow"]
        title: Text
        content: Text
        requirement_ids: list[ID] = Field(min_length=1)
  Thêm design_artifacts vào SynthesizerOutput.
- domain/models.py: thực thể DesignArtifact + PlanRevision.design_artifacts; cập nhật store.
- Thêm mode "design" cho Run. Trong mode này format_synthesize_prompt thay quy tắc 1
  ("actionable, step-by-step plan") bằng: tạo bản thiết kế gồm design_artifacts phủ mọi
  requirement; steps chỉ là kế hoạch kiểm chứng/triển khai tối thiểu.
  Mode greenfield/repo giữ hành vi cũ.
- quality_validator: RULE-COV-001 tính cả requirement_ids của design_artifacts khi mode
  "design"; thêm RULE-DESIGN-001 (mode design mà không có design artifact -> blocker).
- exporter.py: thêm mục "Thiết kế" (markdown + JSON) giữa mục 3 và 4.
- format_propose_prompt: thêm quy tắc "với mỗi requirement, nêu rõ cơ chế và vì sao cơ chế
  đó giải quyết đúng vấn đề của requirement". Dùng ProposalOutput.requirement_coverage
  (hiện không ai đọc) làm đầu vào cho Reviewer.

[F] Semantic review phải độc lập với Synthesizer
- orchestration/roles.py ánh xạ "semantic_review" -> "synthesizer", trong khi prompt tự xưng
  REVIEWER. Kiểm tra role group quyết định gì (model, cấu hình, ngữ cảnh). Nếu nó khiến
  chính model/agent đã viết plan chấm plan, đổi thành "reviewer".
- Kiểm tra IssueResolution.reviewer != command.actor trong policies.py có thực sự được thoả
  mãn ở luồng này không; thêm test.

[G] Reviewer chấm theo từng requirement + hỗ trợ DUPLICATE
- agents/roles.py: thêm
    class RequirementVerdict(AgentContract):
        requirement_id: ID
        restated: Text
        mechanism: Text
        verdict: Literal["PASS","PARTIAL","FAIL"]
        gap: Text | None = None
  Thêm requirement_verdicts vào ReviewOutput. Bắt buộc có đủ verdict cho mọi requirement;
  thiếu thì ValidationError.
- Prompt REVIEW và SEMANTIC_REVIEW: "Với mỗi requirement, diễn đạt lại yêu cầu, chỉ ra cơ chế
  trong plan, rồi phán xét. Nếu cơ chế giải quyết một vấn đề khác với vấn đề của requirement,
  kết luận FAIL." Thêm: "Kiểm tra issue đã tồn tại trước khi tạo mới."
- IssueResolutionReport: mở rộng review_result thành Literal["PASS","FAIL","DUPLICATE"]
  kèm duplicate_of: ID | None; DUPLICATE gọi transition sang IssueStatus.DUPLICATE.
- Cập nhật cách tính passed ở [A] dùng requirement_verdicts.
- Test: plan dùng cơ chế sai vấn đề (ví dụ optimistic locking cho yêu cầu "khôi phục khi
  agent lỗi") với fake LLM trả verdict FAIL -> semantic review passed == False -> PARTIAL.

===== NGHIỆM THU =====
- Full test suite xanh, không skip/xfail mới, không test bị xoá/làm yếu.
- Một run Minesweeper bằng LLM giả vẫn ra FINAL (không làm hỏng luồng cũ).
- Chạy lại test 7 trong mode "design" với constraints và expected_outputs đầy đủ.
- Xuất VERIFY.md: bảng mục A..G -> PASS/FAIL + bằng chứng (lệnh, output, test fail khi revert),
  và rủi ro còn lại.
```
