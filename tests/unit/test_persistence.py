from pathlib import Path

from mllminal.contracts import MessageRole, TaskState
from mllminal.persistence import Store


def test_store_persists_session_and_orders_events(tmp_path: Path) -> None:
    database = tmp_path / "state.db"
    first = Store(database)
    first.initialize()
    session = first.create_session(workspace_root=str(tmp_path))
    message, created = first.add_message(
        session.id,
        MessageRole.USER,
        "inspect this project",
        idempotency_key="message-1",
    )
    duplicate, duplicate_created = first.add_message(
        session.id,
        MessageRole.USER,
        "inspect this project",
        idempotency_key="message-1",
    )

    assert created is True
    assert duplicate_created is False
    assert duplicate.id == message.id
    assert [event.sequence for event in first.list_events(session.id)] == [1, 2]

    second = Store(database)
    second.initialize()
    restored = second.get_session(session.id)
    assert restored.id == session.id
    assert [item.content for item in second.list_messages(session.id)] == ["inspect this project"]


def test_store_enforces_task_transitions(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    session = store.create_session(workspace_root=str(tmp_path))
    task = store.create_task(session.id, "Inspect project", "Inspect project safely")

    planning = store.transition_task(task.id, TaskState.PLANNING)

    assert planning.state is TaskState.PLANNING
