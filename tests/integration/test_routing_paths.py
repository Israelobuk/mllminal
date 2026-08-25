from pathlib import Path

import pytest

from mllminal.agent.provider import MilProviderEvent, MilRequest
from mllminal.agent.routing import MilRoute
from mllminal.agent.runtime import MilRuntime
from mllminal.runtime_store import RuntimeStore


def make_runtime(tmp_path: Path) -> tuple[MilRuntime, RuntimeStore, str]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text("[project]\nname='demo'", encoding="utf-8")
    store = RuntimeStore(tmp_path / "state.db")
    store.initialize()
    session = store.create_session(str(workspace))
    return MilRuntime(store), store, session.id


class RecordingQwenProvider:
    def __init__(self) -> None:
        self.requests: list[MilRequest] = []

    async def stream_conversation(self, request: MilRequest):
        self.requests.append(request)
        response = f"Qwen answer for: {request.user_message}"
        yield MilProviderEvent(event_type="response.started")
        yield MilProviderEvent(event_type="response.delta", text=response)
        yield MilProviderEvent(event_type="response.completed", text=response)

    async def stream_response(self, _request: MilRequest):
        raise AssertionError("safe conversational routes must not enter planning")
        yield


@pytest.mark.asyncio
async def test_chat_route_answers_without_task_or_approval(tmp_path: Path) -> None:
    _default_runtime, store, session_id = make_runtime(tmp_path)
    provider = RecordingQwenProvider()
    runtime = MilRuntime(store, provider=provider)

    response = await runtime.respond(session_id, "hello", "chat-route")

    assert response.route is MilRoute.CHAT
    assert response.response == "Qwen answer for: hello"
    assert len(provider.requests) == 1
    assert store.list_tasks() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("prompt", ["hello", "work with my files", "what can you do"])
async def test_conversational_prompts_are_generated_by_qwen(
    tmp_path: Path, prompt: str
) -> None:
    _default_runtime, store, session_id = make_runtime(tmp_path)
    provider = RecordingQwenProvider()
    runtime = MilRuntime(store, provider=provider)

    response = await runtime.respond(session_id, prompt, f"qwen-{prompt.replace(' ', '-')}")

    assert response.response == f"Qwen answer for: {prompt}"
    assert provider.requests[-1].user_message == prompt
    assert store.list_tasks() == []


@pytest.mark.asyncio
async def test_open_apps_question_stays_local_information(tmp_path: Path) -> None:
    _default_runtime, store, session_id = make_runtime(tmp_path)
    provider = RecordingQwenProvider()
    runtime = MilRuntime(store, provider=provider)

    response = await runtime.respond(session_id, "what apps are open right now?", "apps-route")

    assert response.route is MilRoute.LOCAL_INFORMATION
    assert response.response == "Qwen answer for: what apps are open right now?"
    assert len(provider.requests) == 1
    assert store.list_tasks() == []


@pytest.mark.asyncio
async def test_read_only_route_verifies_tool_result_without_approval(tmp_path: Path) -> None:
    _default_runtime, store, session_id = make_runtime(tmp_path)
    provider = RecordingQwenProvider()
    runtime = MilRuntime(store, provider=provider)

    response = await runtime.respond(session_id, "summarize this project", "read-only-route")

    assert response.route is MilRoute.READ_ONLY_TOOL
    assert provider.requests[0].tool_results[0]["tool_name"] == "project.inspect_metadata"
    assert provider.requests[0].tool_results[0]["verified"] is True
    assert store.list_tasks() == []
