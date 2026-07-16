"""Deterministic task lifecycle validation."""

from mllminal.contracts import TaskState


class InvalidTransitionError(ValueError):
    pass


_TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    TaskState.CREATED: frozenset({TaskState.PLANNING, TaskState.CANCELLED}),
    TaskState.PLANNING: frozenset(
        {TaskState.WAITING_FOR_APPROVAL, TaskState.BLOCKED, TaskState.FAILED, TaskState.CANCELLED}
    ),
    TaskState.WAITING_FOR_APPROVAL: frozenset(
        {TaskState.EXECUTING, TaskState.BLOCKED, TaskState.CANCELLED}
    ),
    TaskState.EXECUTING: frozenset(
        {TaskState.VERIFYING, TaskState.BLOCKED, TaskState.FAILED, TaskState.CANCELLED}
    ),
    TaskState.VERIFYING: frozenset(
        {TaskState.COMPLETED, TaskState.BLOCKED, TaskState.FAILED, TaskState.CANCELLED}
    ),
    TaskState.BLOCKED: frozenset({TaskState.PLANNING, TaskState.CANCELLED}),
    TaskState.COMPLETED: frozenset(),
    TaskState.FAILED: frozenset(),
    TaskState.CANCELLED: frozenset(),
}


def require_transition(current: TaskState, target: TaskState) -> None:
    if target not in _TRANSITIONS[current]:
        raise InvalidTransitionError(f"Cannot transition task from {current} to {target}")
