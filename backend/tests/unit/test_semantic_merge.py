"""Tests for deterministic evidence validation and validator/reviewer merging."""

from __future__ import annotations

from astra_multi.agents.roles import RequirementVerdict, RubricAuditItem
from astra_multi.domain.models import (
    PlanRevision,
    PlanStep,
    Requirement,
    RequirementFulfillment,
    TaskSpec,
    VerdictEvidence,
)
from astra_multi.orchestration.semantic_merge import (
    attach_deterministic_evidence,
    merge_requirement_verdicts,
    validate_evidence,
)


def _task() -> TaskSpec:
    return TaskSpec(
        id="TASK-1",
        goal="Implement the API",
        requirements=[
            Requirement(
                id="REQ-1",
                text="Provide the API module",
                acceptance="Module exists and tests pass",
            )
        ],
    )


def _plan(*, owned: str = "src/api.py", req_id: str = "REQ-1") -> PlanRevision:
    return PlanRevision(
        id="PLAN-1",
        run_id="RUN-1",
        revision=1,
        based_on_revision=0,
        requirements_revision=1,
        snapshot_id=None,
        steps=[
            PlanStep(
                id="STEP-1",
                objective="Implement API",
                requirement_ids=[req_id],
                requirement_fulfillments=[
                    RequirementFulfillment(
                        req_id=req_id,
                        fulfilled_by_section="API module",
                        concrete_deliverable="A concrete API module implementation.",
                        verification_method="pytest tests/test_api.py",
                    )
                ],
                dependencies=[],
                validation="pytest tests/test_api.py",
                deliverables=["src/api.py"],
                completion_criteria=["Tests pass"],
                worker_role="api",
                owned_files=[owned],
            )
        ],
    )


def _evidence(
    *,
    req_id: str = "REQ-1",
    step_id: str | None = "STEP-1",
    checked_path: str | None = "src/api.py",
    validator_rule: str = "RULE-RUBRIC-PASS",
) -> VerdictEvidence:
    return VerdictEvidence(
        req_id=req_id,
        step_id=step_id,
        checked_field="plan.steps[].requirement_fulfillments",
        checked_path=checked_path,
        expected="Concrete deliverable satisfies the acceptance criteria",
        actual="Validator matched the concrete deliverable",
        validator_rule=validator_rule,
    )


def _verdict(
    *,
    verdict: str = "PASS",
    req_id: str = "REQ-1",
    evidence: list[VerdictEvidence] | None = None,
    gap: str | None = None,
) -> RequirementVerdict:
    return RequirementVerdict(
        requirement_id=req_id,
        restated="Provide the API module",
        mechanism="API module",
        verdict=verdict,
        gap=gap,
        evidence=evidence or [],
    )


# ---------------------------------------------------------------------------
# Evidence validation
# ---------------------------------------------------------------------------


def test_validate_evidence_accepts_owned_path_and_covering_step():
    assert (
        validate_evidence(
            _evidence(), requirement_id="REQ-1", plan=_plan()
        )
        is None
    )
    assert (
        validate_evidence(
            _evidence(step_id=None), requirement_id="REQ-1", plan=_plan()
        )
        is None
    )


def test_validate_evidence_rejects_wrong_requirement_and_empty_fields():
    assert "does not match" in validate_evidence(
        _evidence(req_id="REQ-OTHER"), requirement_id="REQ-1", plan=_plan()
    )
    empty = _evidence().model_copy(update={"actual": "   "})
    assert "actual" in validate_evidence(empty, requirement_id="REQ-1", plan=_plan())


def test_validate_evidence_rejects_unknown_step_and_unowned_path():
    assert "unknown step" in validate_evidence(
        _evidence(step_id="STEP-404"), requirement_id="REQ-1", plan=_plan()
    )
    assert "not owned" in validate_evidence(
        _evidence(checked_path="src/other.py"),
        requirement_id="REQ-1",
        plan=_plan(),
    )


def test_validate_evidence_requires_a_covering_step_without_step_id():
    plan = _plan(req_id="REQ-OTHER")
    assert "no plan step covers" in validate_evidence(
        _evidence(step_id=None), requirement_id="REQ-1", plan=plan
    )


def test_validate_evidence_rejects_step_that_does_not_cover_requirement():
    plan = _plan(req_id="REQ-OTHER")
    assert "does not cover" in validate_evidence(
        _evidence(), requirement_id="REQ-1", plan=plan
    )


# ---------------------------------------------------------------------------
# Verdict merging
# ---------------------------------------------------------------------------


def test_validator_pass_with_evidence_and_reviewer_pass_merges_to_pass():
    result = merge_requirement_verdicts(
        _task(),
        _plan(),
        [_verdict(evidence=[_evidence()])],
        [_verdict()],
    )

    assert result.passed is True
    assert result.conflicts == []
    assert result.missing_evidence == []
    assert result.verdicts[0].verdict == "PASS"
    assert result.verdicts[0].evidence[0].checked_path == "src/api.py"


def test_validator_pass_without_evidence_is_downgraded_to_partial():
    result = merge_requirement_verdicts(
        _task(), _plan(), [_verdict()], [_verdict()]
    )

    assert result.passed is False
    assert result.missing_evidence == ["REQ-1"]
    assert result.verdicts[0].verdict == "PARTIAL"
    assert "lacks valid machine-checkable evidence" in result.verdicts[0].gap


def test_reviewer_evidence_cannot_substitute_for_validator_evidence():
    result = merge_requirement_verdicts(
        _task(),
        _plan(),
        [_verdict()],
        [_verdict(evidence=[_evidence()])],
    )

    assert result.verdicts[0].verdict == "PARTIAL"
    assert result.missing_evidence == ["REQ-1"]


def test_invalid_validator_evidence_is_not_accepted():
    result = merge_requirement_verdicts(
        _task(),
        _plan(),
        [_verdict(evidence=[_evidence(step_id="STEP-404")])],
        [_verdict()],
    )

    assert result.verdicts[0].verdict == "PARTIAL"
    assert result.missing_evidence == ["REQ-1"]
    assert any("unknown step" in problem for problem in result.evidence_problems)


def test_validator_pass_conflicting_with_reviewer_fail_is_partial():
    result = merge_requirement_verdicts(
        _task(),
        _plan(),
        [_verdict(evidence=[_evidence()])],
        [_verdict(verdict="FAIL", gap="Missing tests")],
    )

    assert result.passed is False
    assert result.verdicts[0].verdict == "PARTIAL"
    assert result.conflicts == [
        "REQ-1: validator says PASS but reviewer says FAIL"
    ]


def test_validator_fail_is_authoritative_even_when_reviewer_passes():
    result = merge_requirement_verdicts(
        _task(),
        _plan(),
        [_verdict(verdict="FAIL", gap="No implementation")],
        [_verdict()],
    )

    assert result.verdicts[0].verdict == "FAIL"
    assert result.conflicts == [
        "REQ-1: validator says FAIL but reviewer says PASS"
    ]


def test_reviewer_pass_without_validator_verdict_is_partial():
    result = merge_requirement_verdicts(
        _task(), _plan(), [], [_verdict(evidence=[_evidence()])]
    )

    assert result.verdicts[0].verdict == "PARTIAL"
    assert result.missing_evidence == ["REQ-1"]


def test_missing_both_verdicts_is_fail_with_missing_evidence():
    result = merge_requirement_verdicts(_task(), _plan(), [], [])

    assert result.verdicts[0].verdict == "FAIL"
    assert result.missing_evidence == ["REQ-1"]


def test_reviewer_fail_without_validator_verdict_remains_fail():
    result = merge_requirement_verdicts(
        _task(), _plan(), [], [_verdict(verdict="FAIL", gap="No implementation")]
    )

    assert result.verdicts[0].verdict == "FAIL"
    assert result.missing_evidence == []


# ---------------------------------------------------------------------------
# Rubric audit evidence attachment
# ---------------------------------------------------------------------------


def _audit(status: str = "MET", *, evidence=None) -> RubricAuditItem:
    return RubricAuditItem(
        rubric_id="RUBRIC-1",
        req_id="REQ-1",
        status=status,
        evidence=evidence or [],
        notes="reviewer note",
    )


def test_attach_replaces_reviewer_evidence_with_validator_evidence():
    audits, conflicts, missing = attach_deterministic_evidence(
        [_audit(evidence=[_evidence(validator_rule="REVIEWER-CLAIM")])],
        {"REQ-1": _verdict(evidence=[_evidence()])},
    )

    assert conflicts == []
    assert missing == []
    assert audits[0].status == "MET"
    assert audits[0].evidence[0].validator_rule == "RULE-RUBRIC-PASS"


def test_attach_downgrades_met_without_validator_evidence():
    audits, conflicts, missing = attach_deterministic_evidence(
        [_audit(evidence=[_evidence()])],
        {"REQ-1": _verdict()},
    )

    assert conflicts == []
    assert missing == ["REQ-1"]
    assert audits[0].status == "PARTIAL"
    assert audits[0].evidence == []


def test_attach_downgrades_met_when_validator_fails():
    audits, conflicts, missing = attach_deterministic_evidence(
        [_audit()],
        {"REQ-1": _verdict(verdict="FAIL", gap="No implementation")},
    )

    assert missing == []
    assert conflicts == [
        "RUBRIC-1/REQ-1: reviewer says MET but validator says FAIL"
    ]
    assert audits[0].status == "PARTIAL"


def test_attach_downgrades_met_without_any_validator_verdict():
    audits, conflicts, missing = attach_deterministic_evidence([_audit()], {})

    assert conflicts == []
    assert missing == ["REQ-1"]
    assert audits[0].status == "PARTIAL"


def test_attach_leaves_non_met_audits_untouched():
    original = _audit(status="PARTIAL")
    audits, conflicts, missing = attach_deterministic_evidence(
        [original], {"REQ-1": _verdict(evidence=[_evidence()])}
    )

    assert audits == [original]
    assert conflicts == []
    assert missing == []
