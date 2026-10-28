"""Validation of machine-checkable evidence attached to verdicts.

The reviewer model is not trusted to invent proof.  Evidence must reference the
requirement it claims to prove, a committed plan step that covers that
requirement, and (when a path is named) a file owned by that step.
"""

from __future__ import annotations

from .models import PlanRevision, PlanStep, VerdictEvidence
from .paths import PathValidationError, path_key


def _covering_steps(req_id: str, plan: PlanRevision) -> list[PlanStep]:
    matched: list[PlanStep] = []
    for step in plan.steps:
        fulfillment_ids = {
            getattr(rf, "req_id", "")
            for rf in (getattr(step, "requirement_fulfillments", []) or [])
        }
        if req_id in fulfillment_ids or req_id in step.requirement_ids:
            matched.append(step)
    return matched


def _step_owned_keys(step: PlanStep) -> set[str]:
    keys: set[str] = set()
    for raw in step.owned_files:
        try:
            keys.add(path_key(raw))
        except PathValidationError:
            continue
    return keys


def validate_evidence(
    evidence: VerdictEvidence,
    *,
    requirement_id: str,
    plan: PlanRevision,
) -> str | None:
    """Return a human-readable problem, or ``None`` when evidence is valid."""
    if evidence.req_id != requirement_id:
        return (
            f"evidence req_id {evidence.req_id!r} does not match verdict "
            f"requirement {requirement_id!r}"
        )
    for field_name in ("checked_field", "expected", "actual", "validator_rule"):
        if not str(getattr(evidence, field_name, "") or "").strip():
            return f"evidence field {field_name!r} is empty"

    steps_by_id = {step.id: step for step in plan.steps}
    if evidence.step_id is not None:
        step = steps_by_id.get(evidence.step_id)
        if step is None:
            return f"evidence references unknown step {evidence.step_id!r}"
        covering_ids = {
            getattr(rf, "req_id", "")
            for rf in (getattr(step, "requirement_fulfillments", []) or [])
        } | set(step.requirement_ids)
        if requirement_id not in covering_ids:
            return (
                f"evidence step {evidence.step_id!r} does not cover "
                f"requirement {requirement_id!r}"
            )
        candidate_steps = [step]
    else:
        candidate_steps = _covering_steps(requirement_id, plan)
        if not candidate_steps:
            return (
                f"evidence has no step_id and no plan step covers "
                f"requirement {requirement_id!r}"
            )

    if evidence.checked_path is None:
        return None

    try:
        checked_key = path_key(evidence.checked_path)
    except PathValidationError as exc:
        return f"evidence checked_path is invalid: {exc}"

    owned: set[str] = set()
    for step in candidate_steps:
        owned.update(_step_owned_keys(step))
    if checked_key not in owned:
        return (
            f"evidence checked_path {evidence.checked_path!r} is not owned by "
            f"the referenced step(s)"
        )
    return None
