from datetime import UTC

import pytest

from mllminal.contracts import EventEnvelope, TaskState, utc_now
from mllminal.state_machine import InvalidTransitionError, require_transition


def test_utc_now_is_timezone_aware() -> None:
    assert utc_now().tzinfo is UTC


def test_event_sequence_must_be_positive() -> None:
    with pytest.raises(ValueError):
        EventEnvelope(session_id="session", sequence=0, event_type="test", payload={})


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (TaskState.CREATED, TaskState.PLANNING),
        (TaskState.PLANNING, TaskState.WAITING_FOR_APPROVAL),
        (TaskState.EXECUTING, TaskState.VERIFYING),
        (TaskState.VERIFYING, TaskState.COMPLETED),
    ],
)
def test_valid_task_transitions(current: TaskState, target: TaskState) -> None:
    require_transition(current, target)


def test_completed_cannot_be_entered_directly_from_executing() -> None:
    with pytest.raises(InvalidTransitionError):
        require_transition(TaskState.EXECUTING, TaskState.COMPLETED)
