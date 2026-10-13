# Cấu hình Rubric, Template Plan, Intake và Bộ Prompt — Astra Multi

Tài liệu này tổng hợp toàn bộ code và cấu hình thực tế trong codebase **Astra Multi**, bao gồm:
1. **Code Intake & Khởi tạo `TaskSpec`** (`api/schemas.py`, `api/app.py`, `cli.py`, `orchestration/graph.py`)
2. **Toàn bộ Prompt Templates & Output Schemas của các Role (Planner, Reviewer, Synthesizer)** (`agents/roles.py`, `orchestration/roles.py`, `orchestration/graph.py`)
3. **Cấu hình Rubric, Quality Gates & Cách tính `SemanticReviewAssessment.passed`** (`evaluations/scoring.py`, `exports/quality_validator.py`, `exports/finalization.py`, `domain/policies.py`, `api/app.py`, `cli.py`)
4. **Template Plan (Domain Schema, JSON Export & Markdown Export)** (`domain/models.py`, `exports/exporter.py`)

---

## 1. Code Intake & Cách sinh `TaskSpec`

Trong kiến trúc hiện tại, hệ thống **không dùng LLM ở bước Intake để phân tích hay sinh `TaskSpec`**. Thay vào đó, `TaskSpec` được khởi tạo trực tiếp (deterministic) từ dữ liệu đầu vào của người dùng ở API hoặc CLI trước khi đưa vào `SQLiteStore`, còn `intake_node` trong LangGraph chỉ làm nhiệm vụ chuyển pha (`INTAKE -> SNAPSHOT`).

### 1.1. Schema đầu vào ở API (`backend/src/astra_multi/api/schemas.py:10-22`)

```python
class CreateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=1, description="Goal of the architecture design task")
    requirements: list[str] = Field(min_length=1, description="List of requirement statements")
    mode: Literal["greenfield", "repo"] = "greenfield"
    snapshot_path: str | None = None
    idempotency_key: str | None = None
    max_rounds: int = Field(default=2, ge=1, le=10)
    token_limit: int = Field(default=0, ge=0)
    cost_limit: float = Field(default=0.0, ge=0.0)
    call_limit: int = Field(default=0, ge=0)
```

### 1.2. Sinh `TaskSpec` khi tạo Run qua FastAPI (`backend/src/astra_multi/api/app.py:218-250`)

> **Lưu ý quan trọng:**
> - `Requirement.id` được đánh số tuần tự `REQ-001`, `REQ-002`, ...
> - Trường `Requirement.acceptance` đang được **gán cứng (hardcode)** là `"Verified by design and candidate test steps"`.
> - Các trường tùy chọn trong `TaskSpec` (`constraints`, `non_goals`, `acceptance_criteria`, `unknowns`) không có trong `CreateRunRequest` nên luôn nhận giá trị mặc định là danh sách rỗng `[]`.

```python
run_id = f"RUN-{uuid.uuid4().hex[:8]}"
task_id = f"TASK-{run_id}"

requirements = [
    Requirement(
        id=f"REQ-{idx + 1:03d}",
        text=req_text,
        acceptance="Verified by design and candidate test steps",
    )
    for idx, req_text in enumerate(payload.requirements)
]

task = TaskSpec(
    id=task_id,
    goal=payload.goal,
    requirements=requirements,
)

run = Run(
    id=run_id,
    task_id=task.id,
    task_revision=1,
    snapshot_id=None,
    mode=payload.mode,
    config_hash="0" * 64,
    budget=Budget(
        token_limit=payload.token_limit,
        cost_limit=payload.cost_limit,
    ),
)

store.create(task, run, snapshot=None)
```

### 1.3. Sinh `TaskSpec` khi tạo Run qua CLI (`backend/src/astra_multi/cli.py:134-166`)

```python
def cmd_create(store: SQLiteStore, args: argparse.Namespace) -> int:
    import uuid

    run_id = args.run_id or f"RUN-{uuid.uuid4().hex[:8]}"
    task_id = f"TASK-{run_id}"

    reqs = [
        Requirement(
            id=f"REQ-{idx + 1:03d}",
            text=text,
            acceptance="Verified by tests and candidate plan steps",
        )
        for idx, text in enumerate(args.requirements)
    ]

    task = TaskSpec(
        id=task_id,
        goal=args.goal,
        requirements=reqs,
    )

    run = Run(
        id=run_id,
        task_id=task.id,
        task_revision=1,
        snapshot_id=None,
        mode="greenfield",
        config_hash="0" * 64,
    )

    store.create(task, run, snapshot=None)
    print(f"Created run {run_id} for task {task_id}")
    return 0
```

### 1.4. Node `intake_node` trong LangGraph (`backend/src/astra_multi/orchestration/graph.py:352-366`)

Các node đầu đồ thị (`intake_node`, `snapshot_node`, `investigate_node`) hiện chỉ chuyển pha trong domain state mà không gọi LLM hay chạy tool phân tích thêm:

```python
def intake_node(state: OrchestrationState) -> dict:
    ctrl.transition_phase(RunPhase.SNAPSHOT)
    return {
        "round": 0,
        "max_rounds": state.get("max_rounds", 2),
        "events": [f"[INTAKE] Started run {ctrl.lease.run_id}"],
    }

def snapshot_node(state: OrchestrationState) -> dict:
    ctrl.transition_phase(RunPhase.INVESTIGATE)
    return {"events": ["[SNAPSHOT] Snapshot verified"]}

def investigate_node(state: OrchestrationState) -> dict:
    ctrl.transition_phase(RunPhase.INDEPENDENT_ANALYSIS)
    return {"events": ["[INVESTIGATE] Initial inspection complete"]}
```

---

## 2. Toàn bộ Prompt & Output Schemas (Planner, Reviewer, Synthesizer)

### 2.1. Ánh xạ Role Group (`backend/src/astra_multi/orchestration/roles.py`)

```python
ROLE_GROUP: dict[str, str] = {
    # Nodes in graph.py calling LLM
    "planner_analysis": "planner",
    "reviewer_analysis": "reviewer",
    "propose": "planner",
    "review": "reviewer",
    "revise": "synthesizer",
    "semantic_review": "synthesizer",  # Lưu ý: node_name="semantic_review" đang map vào nhóm "synthesizer"
    # Direct canonical roles lookup
    "planner": "planner",
    "reviewer": "reviewer",
    "synthesizer": "synthesizer",
}
```

### 2.2. Output Schemas của cả 3 Role (`backend/src/astra_multi/agents/roles.py:26-182`)

```python
class AgentContract(BaseModel):
    """Base schema for agent outputs. Forbids extra fields like routing/budget overrides."""

    model_config = ConfigDict(extra="forbid", frozen=True)


# --- 1. INDEPENDENT_ANALYSIS (Planner & Reviewer) ---
class AnalysisFinding(AgentContract):
    finding: Text
    evidence_ids: list[ID] = Field(default_factory=list)


class AnalysisOutput(AgentContract):
    """Output schema for INDEPENDENT_ANALYSIS phase."""

    role: Literal["planner", "reviewer"]
    findings: list[Text] = Field(min_length=1)
    risks: list[Text] = Field(default_factory=list)
    assumptions: list[Text] = Field(default_factory=list)
    evidence_ids: list[ID] = Field(default_factory=list)
    marker: str = ""  # Used for testing isolation


# --- 2. PROPOSE (Planner) ---
class ProposalOutput(AgentContract):
    """Output schema for Planner in PROPOSE phase."""

    approach: Text
    alternatives: list[Text] = Field(default_factory=list)
    tradeoffs: list[Text] = Field(default_factory=list)
    requirement_coverage: dict[ID, Text] = Field(
        default_factory=dict,
        description="Map from requirement ID to description of how it is addressed",
    )
    claim_ids: list[ID] = Field(
        default_factory=list,
        description="IDs of established domain claims (CLAIM-...) if any. Leave empty if none.",
    )


# --- 3. REVIEW & SEMANTIC_REVIEW (Reviewer) ---
class IssueReport(AgentContract):
    """An issue raised by Reviewer in REVIEW phase."""

    id: ID | None = Field(
        default=None,
        description="Deterministic issue ID (e.g. 'ISSUE-3a8c1f0d') when assigned",
    )
    claim: Text
    impact: Text
    severity: IssueSeverity = IssueSeverity.WARNING  # blocking | warning | info
    verification_request: Text | None = None
    suggested_resolution: Text
    requirement_ids: list[ID] = Field(default_factory=list)
    evidence_ids: list[ID] = Field(default_factory=list)


class IssueResolutionReport(AgentContract):
    """Reviewer evaluation/resolution for an existing issue."""

    issue_id: ID
    resolution_text: Text = "Resolved based on current plan revision"
    review_result: Literal["PASS", "FAIL"] = "PASS"
    review_note: Text = "Verified in plan revision"
    evidence_ids: list[ID] = Field(default_factory=list)


class ReviewOutput(AgentContract):
    """Output schema for Reviewer in REVIEW phase."""

    issues: list[IssueReport] = Field(default_factory=list)
    summary: Text
    reviewed_evidence_ids: list[ID] = Field(default_factory=list)
    resolutions: list[IssueResolutionReport] = Field(default_factory=list)


# --- 4. REVISE (Synthesizer) ---
class StepDraft(AgentContract):
    objective: Text
    requirement_ids: list[ID] = Field(min_length=1)
    dependencies: list[str] = Field(default_factory=list)
    targets: list[Text] = Field(default_factory=list)
    validation: Text
    deliverables: list[Text] = Field(min_length=1)
    completion_criteria: list[Text] = Field(min_length=1)
    evidence_ids: list[ID] = Field(default_factory=list)

    @field_validator("requirement_ids", mode="before")
    @classmethod
    def normalize_requirement_ids(cls, v: Any) -> list[str]:
        if not v:
            return ["REQ-001"]
        if isinstance(v, list):
            res = [str(x).strip() for x in v if str(x).strip()]
            return res if res else ["REQ-001"]
        return [str(v).strip()]

    @field_validator("deliverables", mode="before")
    @classmethod
    def normalize_deliverables(cls, v: Any) -> list[str]:
        if not v:
            return ["Deliverable artifact"]
        if isinstance(v, list):
            res = [str(x).strip() for x in v if str(x).strip()]
            return res if res else ["Deliverable artifact"]
        return [str(v).strip()]

    @field_validator("completion_criteria", mode="before")
    @classmethod
    def normalize_completion_criteria(cls, v: Any) -> list[str]:
        if not v:
            return ["Completion verified"]
        if isinstance(v, list):
            res = [str(x).strip() for x in v if str(x).strip()]
            return res if res else ["Completion verified"]
        return [str(v).strip()]


class DecisionDraft(AgentContract):
    question: Text
    chosen: Text
    rationale: Text
    alternatives: list[Text] = Field(default_factory=list)
    evidence_ids: list[ID] = Field(default_factory=list)
    related_issue_ids: list[ID] = Field(default_factory=list)


class SynthesizerOutput(AgentContract):
    """Output schema for Synthesizer in REVISE phase."""

    steps: list[StepDraft] = Field(min_length=1)
    decisions: list[DecisionDraft] = Field(default_factory=list)
    risks: list[Text] = Field(default_factory=list)
    issues_addressed: list[ID] = Field(default_factory=list)
    rationale: Text

    @field_validator("issues_addressed", mode="before")
    @classmethod
    def normalize_issues_addressed(cls, v: Any) -> list[str]:
        if not isinstance(v, list):
            return []
        cleaned: list[str] = []
        for idx, item in enumerate(v):
            if not isinstance(item, str):
                continue
            s = item.strip()
            if re.match(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$", s):
                cleaned.append(s.rstrip(":.,; "))
            else:
                m = re.search(r"(ISSUE-[A-Za-z0-9_-]+)", s, re.IGNORECASE)
                if m:
                    cleaned.append(m.group(1).rstrip(":.,; "))
                else:
                    cleaned.append(f"ISSUE-{idx + 1}")
        return cleaned
```

### 2.3. Toàn bộ 5 hàm tạo Prompt (`backend/src/astra_multi/agents/roles.py:188-328`)

Phiên bản prompt hiện tại: `PROMPT_VERSION_V1 = "v1.0"`.

#### 1) `format_independent_analysis_prompt` (Planner & Reviewer — Pha `INDEPENDENT_ANALYSIS`)

```python
def format_independent_analysis_prompt(bundle: ContextBundle) -> list[dict[str, str]]:
    """Prompt for independent analysis.

    Ensures prompt version and instructions enforce clean fact collection and isolation.
    """
    system_message = (
        f"You are the {bundle.role.upper()} in the Astra Multi architecture design system.\n"
        f"Prompt Version: {PROMPT_VERSION_V1}\n"
        "Phase: INDEPENDENT_ANALYSIS\n"
        "Rules:\n"
        "1. Perform independent technical analysis based ONLY on the provided task and snapshot evidence.\n"
        "2. Do not assume any decisions from other peers.\n"
        "3. Output strictly according to the specified AnalysisOutput schema.\n"
        "4. You do not have permissions to modify budget, execution routing, or system state."
    )
    user_message = f"Context:\n{bundle.content}\n\nPlease perform your independent analysis."
    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]
```

#### 2) `format_propose_prompt` (Planner — Pha `PROPOSE`)

```python
def format_propose_prompt(bundle: ContextBundle, analyses: list[AnalysisOutput]) -> list[dict[str, str]]:
    """Prompt for Planner in PROPOSE phase."""
    if '"plan":' in bundle.content:
        analyses_summary = [{"role": a.role, "findings": a.findings} for a in analyses]
    else:
        analyses_summary = [a.model_dump(mode="json") for a in analyses]
    system_message = (
        "You are the PLANNER in Astra Multi.\n"
        f"Prompt Version: {PROMPT_VERSION_V1}\n"
        "Phase: PROPOSE\n"
        "Rules:\n"
        "1. Formulate a cohesive technical proposal covering all task requirements.\n"
        "2. Synthesize findings, risks, and assumptions from earlier analyses.\n"
        "3. Output strictly according to ProposalOutput schema.\n"
        "4. Do not alter canonical run status or budget."
    )
    user_message = (
        f"Context:\n{bundle.content}\n\n"
        f"Independent Analyses:\n{json.dumps(analyses_summary, ensure_ascii=False, separators=(',', ': '))}\n\n"
        "Please generate your proposal."
    )
    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]
```

#### 3) `format_review_prompt` (Reviewer — Pha `REVIEW`)

```python
def format_review_prompt(
    bundle: ContextBundle,
    proposal: ProposalOutput,
    current_plan: dict | None = None,
) -> list[dict[str, str]]:
    """Prompt for Reviewer in REVIEW phase."""
    system_message = (
        "You are the REVIEWER in Astra Multi.\n"
        f"Prompt Version: {PROMPT_VERSION_V1}\n"
        "Phase: REVIEW\n"
        "Rules:\n"
        "1. Rigorously critique the proposal and/or plan for technical feasibility, edge cases, and missing requirements.\n"
        "2. For each identified issue, provide a claim, impact, severity (blocking/warning/info), and suggested resolution.\n"
        "3. Issues must link to evidence or request verification.\n"
        "4. Output strictly according to ReviewOutput schema."
    )
    user_message = (
        f"Context:\n{bundle.content}\n\n"
        f"Proposal under review:\n{json.dumps(proposal.model_dump(mode='json'), ensure_ascii=False, separators=(',', ': '))}\n\n"
    )
    if current_plan and '"plan":' not in bundle.content:
        user_message += f"Current Plan:\n{json.dumps(current_plan, ensure_ascii=False, separators=(',', ': '))}\n\n"
    user_message += "Please provide your review and issues."
    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]
```

#### 4) `format_synthesize_prompt` (Synthesizer — Pha `REVISE`)

> Lưu ý: Trong codebase hàm tạo prompt cho pha `REVISE` được đặt tên là `format_synthesize_prompt` (gọi từ `revise_node` tại `orchestration/graph.py:643`).

```python
def format_synthesize_prompt(
    bundle: ContextBundle,
    proposal: ProposalOutput,
    review: ReviewOutput,
    current_plan: dict | None = None,
) -> list[dict[str, str]]:
    """Prompt for Synthesizer in REVISE phase."""
    system_message = (
        "You are the SYNTHESIZER in Astra Multi.\n"
        f"Prompt Version: {PROMPT_VERSION_V1}\n"
        "Phase: REVISE\n"
        "Rules:\n"
        "1. Combine proposal, review feedback, and resolved issues into an actionable, step-by-step plan.\n"
        "2. Step dependencies must form a strict Directed Acyclic Graph (DAG).\n"
        "3. Every step must have objective, requirement_ids, validation, deliverables, and completion_criteria.\n"
        "4. In issues_addressed, list the exact issue IDs from Review Issues that this plan revision resolves (e.g. ['ISSUE-3a8c1f0d'] or []). Do NOT put sentences or descriptions into issues_addressed.\n"
        "5. Output strictly according to SynthesizerOutput schema."
    )
    user_message = (
        f"Context:\n{bundle.content}\n\n"
        f"Proposal:\n{json.dumps(proposal.model_dump(mode='json'), ensure_ascii=False, separators=(',', ': '))}\n\n"
        f"Review Issues:\n{json.dumps(review.model_dump(mode='json'), ensure_ascii=False, separators=(',', ': '))}\n\n"
    )
    if current_plan and '"plan":' not in bundle.content:
        user_message += f"Current Plan Baseline:\n{json.dumps(current_plan, ensure_ascii=False, separators=(',', ': '))}\n\n"
    user_message += "Please produce the synthesized revision."
    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]
```

#### 5) `format_semantic_review_prompt` (Reviewer — Pha `SEMANTIC_REVIEW`)

```python
def format_semantic_review_prompt(
    bundle: ContextBundle,
    current_plan: dict,
    open_issues: list[dict],
) -> list[dict[str, str]]:
    """Prompt for Reviewer in SEMANTIC_REVIEW phase."""
    system_message = (
        "You are the REVIEWER in Astra Multi.\n"
        f"Prompt Version: {PROMPT_VERSION_V1}\n"
        "Phase: SEMANTIC_REVIEW\n"
        "Rules:\n"
        "1. Rigorously evaluate the newly synthesized plan revision against previous issues and task requirements.\n"
        "2. If an existing issue is adequately addressed in the plan, produce a resolution specifying its exact issue_id from Open Issues (e.g. 'ISSUE-3a8c1f0d'), review_result='PASS' and review_note.\n"
        "3. If new problems remain or are introduced, identify them as issues.\n"
        "4. Output strictly according to ReviewOutput schema."
    )
    user_message = (
        f"Context:\n{bundle.content}\n\n"
        f"Current Plan Revision to Evaluate:\n{json.dumps(current_plan, ensure_ascii=False, separators=(',', ': '))}\n\n"
    )
    if open_issues and '"open_issues":' not in bundle.content:
        user_message += f"Open Issues to evaluate:\n{json.dumps(open_issues, ensure_ascii=False, separators=(',', ': '))}\n\n"
    user_message += "Please provide your review, new issues (if any), and resolutions for addressed issues."
    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]
```

---

## 3. Cấu hình Rubric, Quality Gates & Cách tính `SemanticReviewAssessment.passed`

### 3.1. Cách `SemanticReviewAssessment.passed` được tính và sử dụng trong thực tế

Đây là điểm rất đáng chú ý khi đối chiếu giữa thiết kế (`exports/finalization.py`) và thực thi (`orchestration/graph.py`, `api/app.py`, `cli.py`):

#### A. Định nghĩa `SemanticReviewAssessment` và `FinalizationService` (`backend/src/astra_multi/exports/finalization.py:25-120`)

`FinalizationService.evaluate(state, semantic_review)` nhận vào một đối tượng `SemanticReviewAssessment` có sẵn trường boolean `passed`:

```python
@dataclass
class SemanticReviewAssessment:
    passed: bool
    reviewed_plan_revision: int
    feedback: str
    concerns: list[str]


class FinalizationService:
    """Evaluates whether a candidate plan revision meets the threshold for FINAL certification."""

    def __init__(self, validator: StructuralQualityValidator | None = None) -> None:
        self.validator = validator or StructuralQualityValidator()

    def evaluate(
        self,
        state: RunState,
        semantic_review: SemanticReviewAssessment | None = None,
    ) -> FinalizationDecision:
        # 1. Structural evaluation
        quality_report = self.validator.validate(state)

        if state.run.status == RunStatus.CANCELLED:
            return FinalizationDecision(
                target_status=RunStatus.CANCELLED,
                reason=state.run.stop_reason or "User cancelled run",
                quality_report=quality_report,
                can_finalize=False,
            )

        pending_questions = [q for q in state.questions if q.blocking and q.answer is None]
        if pending_questions:
            return FinalizationDecision(
                target_status=RunStatus.WAITING_FOR_INPUT,
                reason=f"Waiting for answer on {len(pending_questions)} blocking question(s)",
                quality_report=quality_report,
                can_finalize=False,
            )

        if not quality_report.passed:
            blocker_msgs = [v.message for v in quality_report.violations if v.severity.value == "blocker"]
            return FinalizationDecision(
                target_status=RunStatus.PARTIAL,
                reason=f"Structural validation failed: {'; '.join(blocker_msgs)}",
                quality_report=quality_report,
                can_finalize=False,
            )

        # 2. Semantic review checks
        if semantic_review is None:
            return FinalizationDecision(
                target_status=RunStatus.PARTIAL,
                reason="Semantic review assessment not provided",
                quality_report=quality_report,
                can_finalize=False,
            )

        plan_rev = state.plan.revision if state.plan else 0
        if semantic_review.reviewed_plan_revision != plan_rev:
            return FinalizationDecision(
                target_status=RunStatus.PARTIAL,
                reason=(
                    f"Semantic review is stale (reviewed revision "
                    f"{semantic_review.reviewed_plan_revision}, current plan revision is {plan_rev})"
                ),
                quality_report=quality_report,
                can_finalize=False,
            )

        if not semantic_review.passed:
            return FinalizationDecision(
                target_status=RunStatus.PARTIAL,
                reason=f"Semantic review did not pass: {'; '.join(semantic_review.concerns) or semantic_review.feedback}",
                quality_report=quality_report,
                can_finalize=False,
            )

        return FinalizationDecision(
            target_status=RunStatus.FINAL,
            reason="Candidate plan satisfied all structural quality gates and semantic review rubrics.",
            quality_report=quality_report,
            can_finalize=True,
        )
```

#### B. Thực tế trong API (`/api/runs/{run_id}/finalize`) và CLI (`finalize`)

Cả API (`backend/src/astra_multi/api/app.py:783-796`) và CLI (`backend/src/astra_multi/cli.py:295-313`) đều **không đọc kết quả `semantic_review` từ Graph**, mà **tự khởi tạo cứng (hardcode) `passed=True` và `reviewed_plan_revision=plan_rev`**:

```python
# Trích từ backend/src/astra_multi/api/app.py:784-796 (tương tự ở cli.py:304-313)
async def finalize_run(run_id: str) -> dict[str, Any]:
    state = store.load(run_id)
    service = FinalizationService()

    plan_rev = state.plan.revision if state.plan else 0
    assessment = SemanticReviewAssessment(
        passed=True,
        reviewed_plan_revision=plan_rev,
        feedback="Verified against requirements.",
        concerns=[],
    )

    decision = service.evaluate(state, assessment)
```

#### C. Thực tế trong luồng LangGraph (`semantic_review_node` -> `quality_gate_node` -> `export_node`)

Trong `backend/src/astra_multi/orchestration/graph.py`:
1. **`semantic_review_node` (`graph.py:794-926`)** gọi LLM với schema `ReviewOutput` (không sinh `SemanticReviewAssessment`):
   - Duyệt `review_out.resolutions`: gọi `ctrl.resolve_issue(...)` để chuyển các issue được đánh giá `review_result == "PASS"` sang `IssueStatus.RESOLVED`.
   - Duyệt `review_out.issues`: nếu Reviewer phát hiện lỗi mới ở pha này, gọi `ctrl.record_issue(domain_issue)` để thêm issue mới vào `curr_state.issues`.
2. **`quality_gate_node` (`graph.py:928-980`)** kiểm tra kết quả gián tiếp qua `curr_state.issues` và `StructuralQualityValidator`:
   - Nếu `semantic_review_node` không đóng hết các issue `BLOCKING` cũ, hoặc mở thêm issue `BLOCKING` mới, thì `unresolved_blocking` khác rỗng và `StructuralQualityValidator` báo lỗi `RULE-ISSUE-001` -> `gate_passed = False`.
   - Ngược lại, nếu mọi issue `BLOCKING` đều đã `RESOLVED` (kể cả khi `semantic_review_node` sinh thêm issue mức `WARNING` hoặc `INFO`), và không vi phạm cấu trúc DAG/coverage, thì `gate_passed = True`.
3. **`export_node` (`graph.py:982-998`)**:
   ```python
   if not state.get("gate_passed"):
       status = RunStatus.PARTIAL
       reason = state.get("stop_reason") or StopReason.UNRESOLVED_BLOCKERS.value
   elif ctrl.actor in ("P4-quality-service", "quality-service"):
       status = RunStatus.FINAL
       reason = "Certified final plan (passed quality gates)"
   else:
       status = RunStatus.PARTIAL
       reason = "MVP candidate generated (awaiting P4 quality certification)"
   ```
   > Lưu ý: Khi chạy qua `RunWorker` (`api/worker.py:102`), `WorkflowController` được khởi tạo với `actor="api-worker"`, nên kết thúc Graph run luôn dừng ở `PARTIAL` (`"MVP candidate generated (awaiting P4 quality certification)"`) cho tới khi gọi endpoint `/api/runs/{run_id}/finalize` (nơi dùng `actor="P4-quality-service"`).

---

### 3.2. Evaluation Scoring Rubric (`evaluations/scoring.py`)

Rubric đánh giá chất lượng kế hoạch trong bộ benchmark P6 (`evaluations/scoring.py:1-124`):

| Tiêu chí | Thang điểm | Mô tả |
|---|---|---|
| `correctness` | `0.0 - 4.0` | Không có lỗi kiến trúc, lựa chọn đúng design pattern. |
| `completeness` | `0.0 - 4.0` | Độ bao phủ đầy đủ các yêu cầu (`requirements`) và các ràng buộc ngầm/edge cases. |
| `executability` | `0.0 - 4.0` | Đồ thị bước thực thi (DAG) tuần tự rõ ràng, lệnh cụ thể, có deliverables. |
| `evidence_quality` | `0.0 - 4.0` | Tiêu chí hoàn thành (`completion_criteria`) có thể kiểm chứng, bước kiểm tra thực tế. |
| `proportionality` | `0.0 - 4.0` | Giải pháp tương xứng, tránh over-engineering hoặc độ phức tạp suy đoán. |

> Lưu ý: Trong `EvaluationScorer.score_plan` (`evaluations/scoring.py:63-123`), điểm số hiện tại đang được gán tĩnh theo hệ thống (`astra_multi_agent` vs `single_model_baseline`) và danh mục bài toán (`category`) để phục vụ benchmark mô phỏng P6.

---

### 3.3. Structural Quality Validator Rules (`backend/src/astra_multi/exports/quality_validator.py`)

Bộ kiểm định cấu trúc tất định (`StructuralQualityValidator`) kiểm tra `RunState` và trả về `QualityReport`:

| Rule ID | Mức độ (`ViolationSeverity`) | Đối tượng (`entity_ref`) | Điều kiện vi phạm | Hướng khắc phục (`remediation`) |
|---|---|---|---|---|
| `RULE-STRUCT-001` | `blocker` | `run:<run_id>` | Chưa có `PlanRevision` nào được commit (`state.plan is None`). | Sinh và commit một bản plan revision trong pha `REVISE`. |
| `RULE-REF-001` | `blocker` | `step:<step_id>` | `step.requirement_ids` chứa ID không thuộc `state.task.requirements` hiện tại. | Đảm bảo `requirement_ids` của step khớp với `TaskSpec` hiện tại. |
| `RULE-COV-001` | `blocker` | `plan:<plan_id>` | Tập hợp `requirement_ids` của các step không phủ hết 100% `state.task.requirements`. | Thêm hoặc cập nhật các bước kế hoạch để bao phủ mọi requirement. |
| `RULE-UNIQUE-001` | `blocker` | `plan:<plan_id>` | Tồn tại `step.id` bị trùng lặp trong cùng một kế hoạch. | Đảm bảo mỗi bước kế hoạch có ID duy nhất. |
| `RULE-DAG-001` | `blocker` | `step:<step_id>` | `step.dependencies` tham chiếu tới một `step.id` không tồn tại. | Đảm bảo mọi dependency tham chiếu đến `step.id` hợp lệ. |
| `RULE-DAG-002` | `blocker` | `plan:<plan_id>` | Đồ thị phụ thuộc giữa các bước (`dependencies`) có chu trình (cycle). | Loại bỏ phụ thuộc vòng để tạo thành strict DAG. |
| `RULE-ISSUE-001` | `blocker` | `issue:<issue_id>` | Tồn tại issue có `severity == BLOCKING` nhưng `status != RESOLVED`. | Giải quyết và đóng issue trong revision mới hoặc cập nhật requirements. |
| `RULE-STEP-001` | `blocker` | `step:<step_id>` | `step.deliverables` rỗng. | Cung cấp ít nhất 1 deliverable cụ thể cho bước. |
| `RULE-STEP-002` | `blocker` | `step:<step_id>` | `step.completion_criteria` rỗng. | Chỉ định tiêu chí hoàn thành có thể kiểm chứng. |
| `RULE-VAL-001` | `blocker` | `validation:<val_id>` | Validation có `status == NOT_RUN` nhưng chứa `actual` hoặc `exit_code`. | Không ghi kết quả thực thi hoặc mã thoát cho validation chưa chạy. |

---

### 3.4. Chính sách đóng Issue `BLOCKING` (`backend/src/astra_multi/domain/policies.py:88-130`)

Một issue có `severity == IssueSeverity.BLOCKING` chỉ được đóng (`RESOLVED` / `REJECTED`) khi có `resolution` thỏa mãn 1 trong 2 nhánh:
1. **Do thay đổi Requirement (`resolution.requirement_change`):**
   * `change.task_revision == state.task.revision` và `change in state.task_changes`
   * Nội dung hoặc tiêu chí chấp nhận của ít nhất một requirement trong `issue.requirement_ids` đã thay đổi so với revision trước đó.
2. **Do Reviewer độc lập xác nhận trên Plan mới (`domain/policies.py:117-130`):**
   ```python
   elif not (
       state.plan
       and resolution.reviewed_revision == state.plan.revision
       and resolution.reviewed_revision > issue.based_on_revision
       and state.plan.requirements_revision == state.task.revision
       and issue.id in state.plan.issues_addressed
       and resolution.reviewer
       and resolution.reviewer != command.actor
       and resolution.review_result == "PASS"
       and resolution.review_note
   ):
       raise InvalidState(
           "blocking issue requires independent review on the new current plan"
       )
   ```

---

## 4. Template Plan (Domain Model, JSON Export & Markdown Export)

### 4.1. Domain Model của Plan (`backend/src/astra_multi/domain/models.py:294-340`)

```python
class Decision(RunEntity):
    question: Text
    chosen: Text
    rationale: Text
    alternatives: list[Text] = Field(default_factory=list)
    evidence_ids: list[ID] = Field(default_factory=list)
    related_issues: list[ID] = Field(default_factory=list)


class PlanStep(Entity):
    objective: Text
    requirement_ids: list[ID] = Field(min_length=1)
    dependencies: list[ID] = Field(default_factory=list)
    targets: list[Text] = Field(default_factory=list)
    validation: Text
    deliverables: list[Text] = Field(min_length=1)
    completion_criteria: list[Text] = Field(min_length=1)
    evidence_ids: list[ID] = Field(default_factory=list)


class PlanRevision(RunEntity):
    revision: Revision
    based_on_revision: Annotated[int, Field(ge=0, strict=True)]
    requirements_revision: Revision
    snapshot_id: ID | None
    steps: list[PlanStep] = Field(min_length=1)
    decisions: list[Decision] = Field(default_factory=list)
    risks: list[Text] = Field(default_factory=list)
    issues_addressed: list[ID] = Field(default_factory=list)
```

### 4.2. Cấu trúc JSON Export (`PlanExporter.export_json` — `exports/exporter.py:31-109`)

```json
{
  "schema_version": 1,
  "metadata": {
    "run_id": "RUN-001",
    "plan_revision": 1,
    "task_revision": 1,
    "snapshot_id": "SNAP-001",
    "status": "FINAL",
    "stop_reason": "Certified final plan (passed quality gates)",
    "created_at": "2026-10-04T00:00:00+00:00"
  },
  "task": {
    "id": "TASK-001",
    "goal": "Mục tiêu bài toán",
    "requirements": [
      {
        "id": "REQ-001",
        "text": "Mô tả yêu cầu",
        "acceptance": "Tiêu chí nghiệm thu"
      }
    ],
    "constraints": [],
    "non_goals": []
  },
  "architecture": {
    "decisions": [
      {
        "id": "DEC-1",
        "question": "Vấn đề kiến trúc cần quyết định",
        "chosen": "Phương án được chọn",
        "rationale": "Lý do lựa chọn",
        "alternatives": ["Phương án thay thế 1"],
        "evidence_ids": ["EVID-001"]
      }
    ]
  },
  "steps": [
    {
      "id": "STEP-1",
      "objective": "Mục tiêu của bước thực hiện",
      "requirement_ids": ["REQ-001"],
      "dependencies": [],
      "targets": ["src/module.py"],
      "validation": "pytest tests/unit/test_module.py",
      "deliverables": ["Module đã cập nhật và unit test"],
      "completion_criteria": ["Toàn bộ test đạt PASS (exit_code = 0)"],
      "evidence_ids": ["EVID-001"]
    }
  ],
  "issues": [
    {
      "id": "ISSUE-3a8c1f0d",
      "severity": "blocking",
      "status": "resolved",
      "claim": "Mô tả vấn đề",
      "impact": "Tác động nếu không xử lý",
      "suggested_resolution": "Hướng xử lý đề xuất",
      "resolution": {
        "schema_version": 1,
        "text": "Đã bổ sung vào STEP-1",
        "evidence_ids": [],
        "reviewed_revision": 1,
        "reviewer": "reviewer",
        "review_result": "PASS",
        "review_note": "Verified in plan revision",
        "requirement_change": null
      }
    }
  ],
  "evidence": [
    {
      "id": "EVID-001",
      "source_type": "repo",
      "locator": "src/module.py",
      "content_hash": "a1b2c3...",
      "status": "PASS"
    }
  ]
}
```

### 4.3. Template Markdown Export (`PlanExporter.export_markdown` — `exports/exporter.py:111-212`)

```markdown
# <task.goal> — Kế hoạch triển khai

## 1. Thông tin bản kế hoạch

- Run ID: `<run.id>`
- Plan revision: `<plan.revision>`
- TaskSpec revision: `<task.revision>`
- Snapshot ID / manifest hash: `<run.snapshot_id | none (greenfield)>`
- Trạng thái: **<status>**
- Lý do trạng thái: <run.stop_reason | None>
- Ngày tạo: `<run.created_at.isoformat()>`

## 2. Mục tiêu và phạm vi

### Mục tiêu

<task.goal>

### Yêu cầu và tiêu chí chấp nhận

| Requirement ID | Yêu cầu | Tiêu chí chấp nhận |
|---|---|---|
| `<req.id>` | <req.text> | <req.acceptance> |

## 3. Quyết định kiến trúc và trade-off

| Decision ID | Vấn đề | Lựa chọn | Alternatives | Lý do |
|---|---|---|---|---|
| `<dec.id>` | <dec.question> | <dec.chosen> | <dec.alternatives> | <dec.rationale> |

## 4. Các bước thực hiện

### <step.id> — <step.objective>

- **Mục tiêu:** <step.objective>
- **Requirements:** `<req_id_1>`, `<req_id_2>`
- **Phụ thuộc:** `<dep_step_id>` (hoặc `không có`)
- **Đầu ra bàn giao:** <step.deliverables>
- **Cách xác minh:** <step.validation>
- **Tiêu chí hoàn thành:** <step.completion_criteria>

## 5. Issues, rủi ro và trạng thái

| ID | Nội dung | Mức độ | Trạng thái | Hướng giải quyết |
|---|---|---|---|---|
| `<issue.id>` | <issue.claim> | <issue.severity> | <issue.status> | <issue.suggested_resolution> |

## 6. Evidence index

| Evidence ID | Nguồn / locator | Hash | Trạng thái kiểm chứng |
|---|---|---|---|
| `<ev.id>` | `<ev.locator>` | `<ev.content_hash[:16]>...` | <ev.status> |
```
