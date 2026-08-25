from pathlib import Path

import pytest

from mllminal.agent.provider import MilProviderEvent, MilRequest
from mllminal.agent.runtime import MilRuntime
from mllminal.runtime_store import RuntimeStore


class ChatProvider:
    async def stream_conversation(self, _request: MilRequest):
        yield MilProviderEvent(event_type="response.started")
        yield MilProviderEvent(event_type="response.delta", text="Hello.")
        yield MilProviderEvent(event_type="response.completed", text="Hello.")

    async def stream_response(self, _request: MilRequest):
        raise AssertionError("latency test must use chat")
        yield


@pytest.mark.asyncio
async def test_runtime_persists_and_exposes_last_latency_trace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = RuntimeStore(tmp_path / "state.db")
    store.initialize()
    session = store.create_session(str(workspace))
    runtime = MilRuntime(store, provider=ChatProvider())

    await runtime.respond(session.id, "hello", "latency-request")

    latency = runtime.last_latency()
    assert latency["route"] == "chat"
    assert latency["history_size"] == 1
    assert latency["durations_ms"]["total"] is not None
    assert "latency.completed" in [event.event_type for event in store.list_events(session.id)]
