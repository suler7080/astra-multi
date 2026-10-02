from astra_multi.domain.commands import Mutation
from astra_multi.domain.models import CheckpointRef, Lease, OperationRecord, RunState
from astra_multi.domain.policies import RevisionConflict
from astra_multi.domain.repositories import RunRepository


class CheckpointBridge:
    def __init__(self, repository: RunRepository) -> None:
        self.repository = repository

    def reference(self, run_id: str) -> CheckpointRef:
        state = self.repository.load(run_id)
        return CheckpointRef(
            run_id=run_id,
            revision=state.run.revision,
            task_id=state.task.id,
            task_revision=state.task.revision,
            plan_id=state.plan.id if state.plan else None,
        )

    def load(self, checkpoint: CheckpointRef) -> RunState:
        state = self.repository.load(checkpoint.run_id)
        if (
            checkpoint.revision > state.run.revision
            or checkpoint.task_id != state.task.id
        ):
            raise RevisionConflict(
                "checkpoint cannot be ahead of canonical domain state"
            )
        if checkpoint.task_revision > state.task.revision or (
            checkpoint.plan_id is not None
            and checkpoint.plan_id not in {p.id for p in state.plans}
        ):
            raise RevisionConflict("checkpoint references unknown canonical records")
        return state

    def commit(
        self, checkpoint: CheckpointRef, command: Mutation, lease: Lease
    ) -> tuple[OperationRecord, CheckpointRef]:
        self.load(checkpoint)
        result = self.repository.commit(checkpoint.run_id, command, lease)
        return result, self.reference(checkpoint.run_id)
