"""Deterministic merge of validator evidence and reviewer verdicts.

The reviewer model is not trusted to invent proof.  Only evidence produced by
deterministic validators is accepted, and a ``PASS`` without machine-checkable
evidence is downgraded to ``PARTIAL``.  Any disagreement between the validator
and the reviewer is recorded as a conflict so finalization can route the run to
a human instead of silently granting FINAL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from astra_multi.agents.roles import RequirementVerdict
from astra_multi.domain.evidence import validate_evidence
from astra_multi.domain.models import (
    PlanRevision,
    TaskSpec,
    VerdictEvidence,
)

_MISSING = "MISSING"


@dataclass
class SemanticMergeResult:
    """Outcome of merging validator and model verdicts for one plan revision."""

    verdicts: list[RequirementVerdict] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    evidence_problems: list[str] = field(default_factory=list)
    validator_verdicts: dict[str, RequirementVerdict] = field(default_factory=dict)
    model_verdicts: dict[str, RequirementVerdict] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return (
            not self.conflicts
            and not self.missing_evidence
            and bool(self.verdicts)
            and all(verdict.verdict == "PASS" for verdict in self.verdicts)
        )


def _valid_evidence(
    verdict: RequirementVerdict | None,
    *,
    requirement_id: str,
    plan: PlanRevision,
) -> tuple[list[VerdictEvidence], list[str]]:
    if verdict is None:
        return [], []
    valid: list[VerdictEvidence] = []
    problems: list[str] = []
    for evidence in verdict.evidence:
        problem = validate_evidence(
            evidence, requirement_id=requirement_id, plan=plan
        )
        if problem is None:
            valid.append(evidence)
        else:
            problems.append(f"{requirement_id}: {problem}")
    return valid, problems


def _conflict_message(
    req_id: str,
    validator: RequirementVerdict,
    model: RequirementVerdict,
) -> str:
    return (
        f"{req_id}: validator says {validator.verdict} but reviewer says "
        f"{model.verdict}"
    )


def merge_requirement_verdicts(
    task: TaskSpec,
    plan: PlanRevision,
    validator_verdicts: list[RequirementVerdict],
    model_verdicts: list[RequirementVerdict],
) -> SemanticMergeResult:
    """Merge verdicts for every task requirement.

    Rules:
    - validator ``FAIL`` is authoritative;
    - a validator ``PASS`` requires at least one valid evidence item;
    - reviewer ``PASS`` never creates evidence by itself;
    - reviewer/validator disagreement produces ``PARTIAL`` plus a conflict;
    - a missing reviewer verdict is allowed when the validator PASS carries
      valid deterministic evidence; otherwise the requirement is ``PARTIAL``.
    """
    result = SemanticMergeResult(
        validator_verdicts={v.requirement_id: v for v in validator_verdicts},
        model_verdicts={v.requirement_id: v for v in model_verdicts},
    )

    for requirement in task.requirements:
        req_id = requirement.id
        validator = result.validator_verdicts.get(req_id)
        model = result.model_verdicts.get(req_id)
        validator_status = validator.verdict if validator is not None else _MISSING
        model_status = model.verdict if model is not None else _MISSING
        valid_evidence, evidence_problems = _valid_evidence(
            validator, requirement_id=req_id, plan=plan
        )
        result.evidence_problems.extend(evidence_problems)

        if validator_status == "FAIL":
            assert validator is not None
            merged = validator.model_copy(update={"evidence": valid_evidence})
            if model_status == "PASS":
                assert model is not None
                result.conflicts.append(
                    _conflict_message(req_id, validator, model)
                )
        elif validator_status == "PARTIAL":
            assert validator is not None
            merged = validator.model_copy(update={"evidence": valid_evidence})
            if model_status == "PASS":
                assert model is not None
                result.conflicts.append(
                    _conflict_message(req_id, validator, model)
                )
        elif validator_status == "PASS":
            assert validator is not None
            if not valid_evidence:
                detail = "; ".join(evidence_problems) or "no evidence attached"
                merged = validator.model_copy(
                    update={
                        "verdict": "PARTIAL",
                        "gap": (
                            "Validator PASS lacks valid machine-checkable "
                            f"evidence: {detail}"
                        ),
                        "evidence": [],
                    }
                )
                result.missing_evidence.append(req_id)
            elif model_status in ("FAIL", "PARTIAL"):
                assert model is not None
                merged = validator.model_copy(
                    update={
                        "verdict": "PARTIAL",
                        "gap": (
                            "Validator PASS conflicts with reviewer "
                            f"{model_status}: {model.gap or model.mechanism}"
                        ),
                        "evidence": valid_evidence,
                    }
                )
                result.conflicts.append(
                    _conflict_message(req_id, validator, model)
                )
            else:
                # No reviewer verdict is not a conflict: the deterministic
                # validator owns the proof.  A reviewer PASS without evidence
                # is also fine here because model evidence is never trusted.
                merged = validator.model_copy(update={"evidence": valid_evidence})
        else:
            if model_status == "PASS":
                assert model is not None
                merged = model.model_copy(
                    update={
                        "verdict": "PARTIAL",
                        "gap": (
                            "Reviewer PASS has no deterministic validator "
                            "evidence."
                        ),
                        "evidence": [],
                    }
                )
                result.missing_evidence.append(req_id)
            elif model_status in ("FAIL", "PARTIAL"):
                assert model is not None
                merged = model.model_copy(update={"evidence": []})
            else:
                merged = RequirementVerdict(
                    requirement_id=req_id,
                    restated=requirement.text,
                    mechanism="Unverified",
                    verdict="FAIL",
                    gap=f"No validator or reviewer verdict for {req_id}",
                    evidence=[],
                )
                result.missing_evidence.append(req_id)

        result.verdicts.append(merged)

    return result


def attach_deterministic_evidence(
    audits: list[Any],
    validator_verdicts: dict[str, RequirementVerdict],
) -> tuple[list[Any], list[str], list[str]]:
    """Replace reviewer-supplied proof on MET audits with validator evidence.

    Returns ``(audits, conflicts, missing_evidence)``.  A MET audit whose
    requirement has no valid deterministic evidence is downgraded to PARTIAL.
    """
    updated: list[object] = []
    conflicts: list[str] = []
    missing: list[str] = []

    for audit in audits:
        status = getattr(audit, "status", None)
        req_id = getattr(audit, "req_id", "")
        rubric_id = getattr(audit, "rubric_id", "R")
        if status != "MET":
            updated.append(audit)
            continue

        validator = validator_verdicts.get(req_id)
        if validator is None:
            downgraded = audit.model_copy(
                update={
                    "status": "PARTIAL",
                    "evidence": [],
                    "notes": (
                        f"{getattr(audit, 'notes', '')} [validator has no "
                        f"verdict for {req_id}]"
                    ).strip(),
                }
            )
            updated.append(downgraded)
            missing.append(req_id)
            continue

        if validator.verdict != "PASS":
            downgraded = audit.model_copy(
                update={
                    "status": "PARTIAL",
                    "evidence": list(validator.evidence),
                    "notes": (
                        f"{getattr(audit, 'notes', '')} [validator verdict is "
                        f"{validator.verdict}]"
                    ).strip(),
                }
            )
            updated.append(downgraded)
            conflicts.append(
                f"{rubric_id}/{req_id}: reviewer says MET but validator says "
                f"{validator.verdict}"
            )
            continue

        if not validator.evidence:
            downgraded = audit.model_copy(
                update={
                    "status": "PARTIAL",
                    "evidence": [],
                    "notes": (
                        f"{getattr(audit, 'notes', '')} [no deterministic "
                        "evidence]"
                    ).strip(),
                }
            )
            updated.append(downgraded)
            missing.append(req_id)
            continue

        updated.append(
            audit.model_copy(update={"evidence": list(validator.evidence)})
        )

    return updated, conflicts, missing
