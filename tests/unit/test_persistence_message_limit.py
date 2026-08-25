from pathlib import Path

from mllminal.contracts import MessageRole
from mllminal.persistence import Store


def test_store_can_load_only_the_newest_messages_in_order(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    session = store.create_session(workspace_root=str(tmp_path))
    for index in range(3):
        store.add_message(
            session.id,
            MessageRole.USER,
            f"message-{index}",
            idempotency_key=f"message-{index}",
        )

    limited = store.list_messages(session.id, limit=2)

    assert [message.content for message in limited] == ["message-1", "message-2"]
