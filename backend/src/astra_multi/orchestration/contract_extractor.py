"""Contract Extractor: classifies raw requirement text into TECH / DELIV / ORG types.

Rule-based heuristics — no LLM call required — to keep intake fast and
deterministic. The classifier inspects keyword patterns in the requirement
text and returns a (RequirementType, ArtifactType, list[str]) tuple so
create_run can build richly-typed Requirement objects with prefixed IDs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from astra_multi.domain.models import (
    ArtifactType,
    Requirement,
    RequirementType,
    RubricChecklist,
    RubricItem,
    TaskSpec,
)

# ---------------------------------------------------------------------------
# Keyword tables
# ---------------------------------------------------------------------------

# Patterns that strongly signal a DELIVERABLE (something tangible to produce)
_DELIV_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\b(sơ đồ|diagram|chart|flowchart|architecture diagram|sequence diagram)\b",
        r"\b(directory tree|cây thư mục|file structure|folder structure)\b",
        r"\b(specification|đặc tả|thiết kế|design doc|markdown doc)\b",
        r"\b(runbook|playbook|hướng dẫn vận hành)\b",
        r"\b(schema|contract|interface definition|api schema)\b",
        r"\b(layout|header.*footer|footer.*header|component|partial|template)\b",
        r"\b(code snippet|sample code|example implementation)\b",
        r"\b(output|deliverable|bàn giao|kết quả)\b",
        r"\b(report|báo cáo|summary|tóm tắt)\b",
    ]
]

# Patterns that strongly signal ORG requirements
_ORG_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\b(bảng phân công|assignment table|work breakdown|ma trận phân công)\b",
        r"\b(phân công|assignment|assign|member|thành viên|lập trình viên|developer)\b",
        r"\b(team|nhóm|group)\b",
        r"\b(commit|branch|pull request|merge|review)\b",
        r"\b(ownership|quyền sở hữu|owner|responsible|trách nhiệm)\b",
        r"\b(4 (người|member|developer|lập trình viên))\b",
        r"\b(workflow|quy trình|process|procedure)\b",
    ]
]

# Patterns that signal TECH constraints
_TECH_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\b(không dùng|không sử dụng|no framework|without|cấm|banned|forbidden)\b",
        r"\b(file://|localhost|static hosting|không có server|no backend)\b",
        r"\b(browser|trình duyệt|IE|Chrome|Firefox|Safari)\b",
        r"\b(bootstrap|tailwind|css framework|library)\b",
        r"\b(mockapi|mock api|api endpoint|rest api|fetch|ajax|xhr)\b",
        r"\b(performance|tốc độ|latency|throughput|memory)\b",
        r"\b(security|bảo mật|auth|authentication|token|jwt)\b",
        r"\b(timeout|retry|circuit breaker|fault tolerance)\b",
        r"\b(environment|môi trường|production|staging|dev)\b",
        r"\b(es module|import|require|bundler|webpack|vite|build step)\b",
    ]
]

# Artifact type inference from keyword patterns
_ARTIFACT_MAP: list[tuple[re.Pattern[str], ArtifactType]] = [
    (re.compile(r"\b(sơ đồ thư mục|directory tree|cây thư mục|folder structure|file structure)\b", re.IGNORECASE), ArtifactType.DIRECTORY_TREE),
    (re.compile(r"\b(bảng phân công|assignment table|ma trận phân công|work breakdown)\b", re.IGNORECASE), ArtifactType.ASSIGNMENT_TABLE),
    (re.compile(r"\b(sơ đồ|architecture diagram|diagram|flowchart)\b", re.IGNORECASE), ArtifactType.ARCHITECTURE_DIAGRAM),
    (re.compile(r"\b(sequence diagram|luồng dữ liệu|data flow|sequence flow)\b", re.IGNORECASE), ArtifactType.SEQUENCE_FLOW),
    (re.compile(r"\b(state machine|trạng thái|state diagram)\b", re.IGNORECASE), ArtifactType.STATE_MACHINE),
    (re.compile(r"\b(schema|contract|api schema|interface)\b", re.IGNORECASE), ArtifactType.API_SCHEMA),
    (re.compile(r"\b(layout|header.*footer|footer.*header|partials|component|code snippet|sample code|example implementation|đoạn code)\b", re.IGNORECASE), ArtifactType.CODE_SNIPPET),
]


# ---------------------------------------------------------------------------
# Core classification logic
# ---------------------------------------------------------------------------

@dataclass
class ClassifiedRequirement:
    text: str
    req_type: RequirementType
    expected_artifact_type: ArtifactType
    acceptance_criteria: list[str] = field(default_factory=list)
    verifiable_deliverable: str | None = None


def _score_text(text: str, patterns: list[re.Pattern[str]]) -> int:
    """Return count of pattern matches in text."""
    return sum(1 for p in patterns if p.search(text))


def classify_requirement(text: str, is_expected_output: bool = False) -> ClassifiedRequirement:
    """Classify a single requirement string.

    Args:
        text: The raw requirement text.
        is_expected_output: If True the caller signals this came from
            ``expected_outputs`` — biases classification toward DELIV.

    Returns:
        A ClassifiedRequirement with type, artifact type, verifiable_deliverable, and acceptance_criteria list.
    """
    t = text.strip()

    # Score each category
    deliv_score = _score_text(t, _DELIV_PATTERNS) + (2 if is_expected_output else 0)
    org_score = _score_text(t, _ORG_PATTERNS)
    tech_score = _score_text(t, _TECH_PATTERNS)

    # Determine type by highest score; TECH is the default tiebreak
    if org_score > deliv_score and org_score > tech_score:
        req_type = RequirementType.ORG
    elif deliv_score >= org_score and deliv_score > tech_score:
        req_type = RequirementType.DELIV
    elif deliv_score == 0 and org_score == 0 and tech_score == 0 and is_expected_output:
        # expected_output with no keyword match → still DELIV
        req_type = RequirementType.DELIV
    else:
        req_type = RequirementType.TECH

    # Infer artifact type
    artifact_type = ArtifactType.NARRATIVE
    for pattern, candidate in _ARTIFACT_MAP:
        if pattern.search(t):
            artifact_type = candidate
            break

    # Determine verifiable deliverable name
    if artifact_type != ArtifactType.NARRATIVE:
        verifiable_deliverable = artifact_type.value
    elif req_type == RequirementType.DELIV:
        verifiable_deliverable = "concrete_deliverable"
    elif req_type == RequirementType.ORG:
        verifiable_deliverable = "assignment_matrix"
    else:
        verifiable_deliverable = None

    # Auto-generate acceptance_criteria
    acceptance_criteria = _derive_acceptance_criteria(t, req_type, artifact_type)

    return ClassifiedRequirement(
        text=t,
        req_type=req_type,
        expected_artifact_type=artifact_type,
        acceptance_criteria=acceptance_criteria,
        verifiable_deliverable=verifiable_deliverable,
    )


def _derive_acceptance_criteria(
    text: str, req_type: RequirementType, artifact_type: ArtifactType
) -> list[str]:
    """Generate a minimal acceptance checklist from text + type."""
    criteria: list[str] = []

    if artifact_type == ArtifactType.DIRECTORY_TREE:
        criteria.append("Plan contains an explicit directory/file tree diagram.")
        criteria.append("Tree shows shared files (CSS, JS, HTML partials) separately from feature folders.")
    elif artifact_type == ArtifactType.ASSIGNMENT_TABLE:
        criteria.append("Plan contains a table mapping each team member to specific files/modules.")
        criteria.append("No two members own the same file (no conflict).")
    elif artifact_type == ArtifactType.ARCHITECTURE_DIAGRAM:
        criteria.append("Plan contains a labelled architecture or component diagram.")
    elif artifact_type == ArtifactType.SEQUENCE_FLOW:
        criteria.append("Plan contains a step-by-step data-flow or sequence diagram.")
    elif artifact_type == ArtifactType.API_SCHEMA:
        criteria.append("Plan defines the API schema / contract with field types.")
    elif artifact_type == ArtifactType.CODE_SNIPPET:
        criteria.append("Plan includes a concrete code example or skeleton.")

    if req_type == RequirementType.TECH:
        criteria.append(f"Plan explicitly addresses the technical constraint: {text[:120]}")
    elif req_type == RequirementType.DELIV:
        criteria.append(f"Plan contains a deliverable satisfying: {text[:120]}")
    elif req_type == RequirementType.ORG:
        criteria.append(f"Plan contains an organisational artefact satisfying: {text[:120]}")

    return criteria


# ---------------------------------------------------------------------------
# Intake-level batch classification with ID assignment
# ---------------------------------------------------------------------------

def build_typed_id(req_type: RequirementType, counter: int) -> str:
    """Return a prefixed requirement ID, e.g. REQ-TECH-001."""
    return f"REQ-{req_type.value}-{counter:03d}"


def classify_all(
    requirements_raw: list[str | dict],
    expected_outputs: list[str],
) -> list[tuple[str, ClassifiedRequirement]]:
    """Classify all raw requirements and expected_outputs, assign typed IDs.

    Returns a list of (id, ClassifiedRequirement) tuples in insertion order.
    Counters are per-type so IDs are contiguous within each type group.
    """
    counters: dict[RequirementType, int] = {t: 0 for t in RequirementType}
    result: list[tuple[str, ClassifiedRequirement]] = []

    # Process explicit requirements first
    for raw in requirements_raw:
        if isinstance(raw, str):
            text = raw.strip()
        elif isinstance(raw, dict):
            text = str(raw.get("text", "")).strip()
        else:
            # RequirementInput pydantic model
            text = raw.text.strip()

        classified = classify_requirement(text, is_expected_output=False)
        counters[classified.req_type] += 1
        req_id = build_typed_id(classified.req_type, counters[classified.req_type])
        result.append((req_id, classified))

    # Then expected_outputs (always default-DELIV biased)
    for out_text in expected_outputs:
        text = str(out_text).strip()
        classified = classify_requirement(text, is_expected_output=True)
        counters[classified.req_type] += 1
        req_id = build_typed_id(classified.req_type, counters[classified.req_type])
        result.append((req_id, classified))

    return result


# ---------------------------------------------------------------------------
# Intake Gate: Deliverable Noun Gap Detection and Reconciliation
# ---------------------------------------------------------------------------

@dataclass
class DeliverableNounRule:
    name: str
    detection_pattern: re.Pattern[str]
    coverage_pattern: re.Pattern[str]
    expected_artifact_type: ArtifactType
    req_type: RequirementType
    fallback_title: str


_DELIVERABLE_RULES: list[DeliverableNounRule] = [
    DeliverableNounRule(
        name="directory_tree",
        detection_pattern=re.compile(r"\b(sơ đồ thư mục|cây thư mục|directory tree|file structure|folder structure)\b", re.IGNORECASE),
        coverage_pattern=re.compile(r"\b(thư mục|directory tree|folder structure|file structure)\b", re.IGNORECASE),
        expected_artifact_type=ArtifactType.DIRECTORY_TREE,
        req_type=RequirementType.DELIV,
        fallback_title="Sơ đồ cây thư mục chi tiết (directory tree)",
    ),
    DeliverableNounRule(
        name="assignment_table",
        detection_pattern=re.compile(r"\b(bảng phân công|ma trận phân công|assignment table|phân công.*(4|người|lập trình viên|thành viên|developer))\b", re.IGNORECASE),
        coverage_pattern=re.compile(r"\b(phân công|assignment|ma trận phân công)\b", re.IGNORECASE),
        expected_artifact_type=ArtifactType.ASSIGNMENT_TABLE,
        req_type=RequirementType.ORG,
        fallback_title="Bảng phân công công việc không xung đột file cho các thành viên",
    ),
    DeliverableNounRule(
        name="layout_reuse",
        detection_pattern=re.compile(r"\b(tái sử dụng layout|layout dùng lại|layout.*header|header.*footer|partials|component layout)\b", re.IGNORECASE),
        coverage_pattern=re.compile(r"\b(layout|header.*footer|footer.*header|partials)\b", re.IGNORECASE),
        expected_artifact_type=ArtifactType.CODE_SNIPPET,
        req_type=RequirementType.DELIV,
        fallback_title="Giải pháp tái sử dụng layout Header/Footer (partials/components)",
    ),
    DeliverableNounRule(
        name="api_layer",
        detection_pattern=re.compile(r"\b(lớp api|tách lớp api|api layer|api service|quy ước tách lớp)\b", re.IGNORECASE),
        coverage_pattern=re.compile(r"\b(lớp api|tách lớp|api layer|api service|quy ước tách lớp)\b", re.IGNORECASE),
        expected_artifact_type=ArtifactType.API_SCHEMA,
        req_type=RequirementType.DELIV,
        fallback_title="Quy ước tách lớp API riêng biệt và cơ chế giao tiếp MockAPI",
    ),
    DeliverableNounRule(
        name="data_flow",
        detection_pattern=re.compile(r"\b(sơ đồ kiến trúc|luồng dữ liệu|data flow|architecture diagram|sequence diagram)\b", re.IGNORECASE),
        coverage_pattern=re.compile(r"\b(kiến trúc|luồng dữ liệu|data flow|sequence|diagram)\b", re.IGNORECASE),
        expected_artifact_type=ArtifactType.ARCHITECTURE_DIAGRAM,
        req_type=RequirementType.DELIV,
        fallback_title="Sơ đồ kiến trúc hệ thống và luồng dữ liệu",
    ),
]


def detect_deliverable_gaps(task: TaskSpec) -> list[ClassifiedRequirement]:
    """Scan task goal and constraints for deliverable nouns that lack corresponding REQ-DELIV or REQ-ORG.

    Returns a list of missing ClassifiedRequirement objects that need to be synthesized.
    """
    text_corpus = f"{task.goal} {' '.join(task.constraints)} {' '.join(task.non_goals)}"
    existing_deliv_or_org = [
        r for r in task.requirements
        if getattr(r, "req_type", None) in (RequirementType.DELIV, RequirementType.ORG)
    ]

    missing: list[ClassifiedRequirement] = []
    for rule in _DELIVERABLE_RULES:
        if rule.detection_pattern.search(text_corpus):
            # Check if covered by existing REQ-DELIV / REQ-ORG
            covered = False
            for req in existing_deliv_or_org:
                if req.expected_artifact_type == rule.expected_artifact_type and rule.expected_artifact_type != ArtifactType.NARRATIVE:
                    covered = True
                    break
                if rule.coverage_pattern.search(req.text):
                    covered = True
                    break
            if not covered:
                missing.append(
                    ClassifiedRequirement(
                        text=rule.fallback_title,
                        req_type=rule.req_type,
                        expected_artifact_type=rule.expected_artifact_type,
                        acceptance_criteria=_derive_acceptance_criteria(
                            rule.fallback_title, rule.req_type, rule.expected_artifact_type
                        ),
                        verifiable_deliverable=(
                            rule.expected_artifact_type.value
                            if rule.expected_artifact_type != ArtifactType.NARRATIVE
                            else None
                        ),
                    )
                )

    return missing


def reconcile_intake_contracts(
    task: TaskSpec, gaps: list[ClassifiedRequirement]
) -> tuple[TaskSpec, list[Requirement]]:
    """Synthesize new typed Requirement objects for missing deliverables and append to task.

    Returns (new_task_spec, added_requirements).
    """
    if not gaps:
        return task, []

    # Count existing per type
    counters: dict[RequirementType, int] = {t: 0 for t in RequirementType}
    for r in task.requirements:
        rtype = getattr(r, "req_type", RequirementType.TECH)
        counters[rtype] += 1

    added: list[Requirement] = []
    new_reqs = list(task.requirements)
    for gap in gaps:
        counters[gap.req_type] += 1
        req_id = build_typed_id(gap.req_type, counters[gap.req_type])
        acc = f"Plan nêu cơ chế cụ thể đáp ứng yêu cầu này và cách kiểm chứng: {gap.text}"
        new_req = Requirement(
            id=req_id,
            text=gap.text,
            acceptance=acc,
            req_type=gap.req_type,
            expected_artifact_type=gap.expected_artifact_type,
            acceptance_criteria=gap.acceptance_criteria,
            verifiable_deliverable=gap.verifiable_deliverable,
        )
        added.append(new_req)
        new_reqs.append(new_req)

    revised_task = TaskSpec(
        id=task.id,
        revision=task.revision + 1,
        goal=task.goal,
        requirements=new_reqs,
        constraints=task.constraints,
        non_goals=task.non_goals,
        acceptance_criteria=task.acceptance_criteria,
        unknowns=task.unknowns,
    )
    return revised_task, added


def generate_evaluation_rubric(task: TaskSpec) -> RubricChecklist:
    """Generate an evaluation rubric checklist from task requirements and acceptance criteria."""
    items: list[RubricItem] = []
    for req in task.requirements:
        cat = getattr(req, "req_type", RequirementType.TECH)
        cat_val = getattr(cat, "value", str(cat))
        if cat_val not in ("TECH", "DELIV", "ORG"):
            cat_val = "TECH"

        crit_list = req.acceptance_criteria if getattr(req, "acceptance_criteria", None) else []
        if crit_list:
            for idx, crit in enumerate(crit_list, start=1):
                items.append(
                    RubricItem(
                        rubric_id=f"RUBRIC-{req.id}-{idx}",
                        req_id=req.id,
                        category=cat_val,  # type: ignore[arg-type]
                        criterion=crit,
                        expected_artifact=getattr(req, "verifiable_deliverable", None),
                    )
                )
        else:
            items.append(
                RubricItem(
                    rubric_id=f"RUBRIC-{req.id}-1",
                    req_id=req.id,
                    category=cat_val,  # type: ignore[arg-type]
                    criterion=req.acceptance or req.text,
                    expected_artifact=getattr(req, "verifiable_deliverable", None),
                )
            )
    return RubricChecklist(items=items)

