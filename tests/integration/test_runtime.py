import json
from pathlib import Path

import httpx
import pytest

from mllminal.agent.ollama import OllamaClient
from mllminal.agent.provider import MilProviderEvent, MilRequest, QwenMilProvider
from mllminal.agent.runtime import MilRuntime, ProviderFailure
from mllminal.contracts import ApprovalStatus, MessageRole, TaskState
from mllminal.runtime_store import RuntimeStore


def make_runtime(tmp_path: Path) -> tuple[MilRuntime, RuntimeStore, str]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "pyproject.toml").write_text("[project]\nname='demo'", encoding="utf-8")
    store = RuntimeStore(tmp_path / "state.db")
    store.initialize()
    session = store.create_session(str(workspace))
    return MilRuntime(store), store, session.id


@pytest.mark.asyncio
async def test_approved_plan_executes_verifies_and_completes(tmp_path: Path) -> None:
    runtime, store, session_id = make_runtime(tmp_path)
    pending = await runtime.submit(session_id, "inspect this project", "request-1")
    completed = runtime.decide(pending.approval.id, ApprovalStatus.APPROVED, "approved-1")

    assert pending.task.state is TaskState.WAITING_FOR_APPROVAL
    assert completed.state is TaskState.COMPLETED
    assert store.list_executions(completed.id)[0].succeeded is True
    assert store.list_verifications(completed.id)[0].succeeded is True


@pytest.mark.asyncio
async def test_rejected_plan_executes_nothing_and_blocks(tmp_path: Path) -> None:
    runtime, store, session_id = make_runtime(tmp_path)
    pending = await runtime.submit(session_id, "inspect this project", "request-1")
    blocked = runtime.decide(pending.approval.id, ApprovalStatus.REJECTED, "rejected-1")

    assert blocked.state is TaskState.BLOCKED
    assert blocked.blocker == "approval_rejected"
    assert store.list_executions(blocked.id) == []


@pytest.mark.asyncio
async def test_duplicate_submission_returns_original_task(tmp_path: Path) -> None:
    runtime, store, session_id = make_runtime(tmp_path)
    first = await runtime.submit(session_id, "inspect this project", "same-key")
    second = await runtime.submit(session_id, "inspect this project", "same-key")

    assert second.task.id == first.task.id
    assert len(store.list_tasks()) == 1


class InterruptedProvider:
    async def stream_response(self, _request: MilRequest):
        raise RuntimeError("stream interrupted")
        yield


@pytest.mark.asyncio
async def test_interrupted_duplicate_submission_can_retry_and_answer(tmp_path: Path) -> None:
    _default_runtime, store, session_id = make_runtime(tmp_path)
    interrupted = MilRuntime(store, provider=InterruptedProvider())

    with pytest.raises(RuntimeError, match="stream interrupted"):
        await interrupted.submit(session_id, "inspect this project", "retry-key")

    recovered = await MilRuntime(store).submit(session_id, "inspect this project", "retry-key")

    assert recovered.task.state is TaskState.WAITING_FOR_APPROVAL
    assert len(store.list_tasks()) == 1


@pytest.mark.asyncio
async def test_provider_stream_events_are_persisted_before_submit_returns(tmp_path: Path) -> None:
    runtime, store, session_id = make_runtime(tmp_path)

    await runtime.submit(session_id, "inspect this project", "streamed-request")

    event_types = [event.event_type for event in store.list_events(session_id)]
    assert event_types.index("response.started") < event_types.index("plan.created")
    assert "response.delta" in event_types
    assert "response.completed" in event_types
    assert "plan.proposed" in event_types


class UnavailableProvider:
    async def stream_response(self, _request: MilRequest):
        yield MilProviderEvent(
            event_type="provider.failed",
            text="Local model server is unavailable.",
            detail={"category": "unavailable"},
        )


class FastChatProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def stream_conversation(self, _request: MilRequest):
        self.calls += 1
        yield MilProviderEvent(event_type="response.started")
        yield MilProviderEvent(event_type="response.delta", text="Hello from Mil.")
        yield MilProviderEvent(event_type="response.completed", text="Hello from Mil.")

    async def stream_response(self, _request: MilRequest):
        raise AssertionError("fast conversational input must not enter planning")
        yield


@pytest.mark.asyncio
async def test_repeated_chat_uses_conversation_context_without_generated_response_cache(
    tmp_path: Path,
) -> None:
    _default_runtime, store, session_id = make_runtime(tmp_path)
    provider = FastChatProvider()
    runtime = MilRuntime(store, provider=provider)

    first = await runtime.respond(session_id, "hi", "chat-1")
    second = await runtime.respond(session_id, "hi", "chat-2")

    assert first.cached is False
    assert second.cached is False
    assert second.response == "Hello from Mil."
    assert provider.calls == 2
    assert store.list_tasks() == []
    assert [message.role for message in store.list_messages(session_id)] == [
        MessageRole.USER,
        MessageRole.MIL,
        MessageRole.USER,
        MessageRole.MIL,
    ]


def test_runtime_route_is_not_limited_to_exact_greetings(tmp_path: Path) -> None:
    runtime, _store, _session_id = make_runtime(tmp_path)

    assert runtime.is_fast_path_request("hi") is True
    assert runtime.is_fast_path_request("what does MLLminal do?") is True
    assert runtime.is_fast_path_request("summarize this project") is True
    assert runtime.is_fast_path_request("list the files in this folder") is True
    assert runtime.is_fast_path_request("open the report") is False


@pytest.mark.asyncio
async def test_provider_failure_creates_no_fabricated_plan_or_approval(tmp_path: Path) -> None:
    _default_runtime, store, session_id = make_runtime(tmp_path)
    runtime = MilRuntime(store, provider=UnavailableProvider())

    with pytest.raises(ProviderFailure) as failure:
        await runtime.submit(session_id, "inspect this project", "unavailable-request")

    task = failure.value.task
    assert task.state is TaskState.FAILED
    assert task.blocker == "unavailable"
    assert store.list_approvals(task.id) == []
    assert "provider.failed" in [event.event_type for event in store.list_events(session_id)]


@pytest.mark.asyncio
async def test_runtime_persists_provider_metadata_for_completed_response(tmp_path: Path) -> None:
    runtime, store, session_id = make_runtime(tmp_path)

    pending = await runtime.submit(session_id, "inspect this project", "metadata-request")

    metadata = store.get_provider_metadata(pending.task.id)
    assert metadata.provider == "deterministic"
    assert metadata.prompt_version == "v1"
    assert metadata.completion_status == "completed"
    assert metadata.validation_succeeded is True
    assert metadata.retry_count == 0


@pytest.mark.asyncio
async def test_post_execution_summary_uses_verified_tool_output_only(tmp_path: Path) -> None:
    runtime, store, session_id = make_runtime(tmp_path)
    pending = await runtime.submit(session_id, "inspect this project", "summary-request")

    runtime.decide(pending.approval.id, ApprovalStatus.APPROVED, "summary-approval")

    messages = store.list_messages(session_id)
    assert messages[-1].role is MessageRole.MIL
    assert "Verified tool result" in messages[-1].content
    assert "project_type" in messages[-1].content


@pytest.mark.asyncio
async def test_fake_ollama_stream_creates_validated_qwen_plan_and_metadata(tmp_path: Path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        envelope = {
            "response": "I can inspect after approval.",
            "plan": {
                "title": "Inspect",
                "steps": [
                    {
                        "step_id": "one",
                        "description": "Inspect metadata",
                        "tool": {"name": "project.inspect_metadata", "arguments": {}},
                    }
                ],
            },
        }
        body = "\n".join(
            [
                json.dumps(
                    {
                        "message": {"content": json.dumps(envelope)},
                        "done": True,
                        "prompt_eval_count": 4,
                        "eval_count": 3,
                    }
                ),
                "",
            ]
        )
        return httpx.Response(200, content=body.encode())

    _default_runtime, store, session_id = make_runtime(tmp_path)
    provider = QwenMilProvider(
        OllamaClient("http://ollama.test", "qwen:test", transport=httpx.MockTransport(handler))
    )
    runtime = MilRuntime(store, provider=provider)
    pending = await runtime.submit(session_id, "inspect this project", "fake-ollama-request")

    metadata = store.get_provider_metadata(pending.task.id)
    assert pending.plan.steps[0].proposal.tool_name == "project.inspect_metadata"
    assert metadata.provider == "qwen"
    assert metadata.input_tokens == 4
    assert metadata.output_tokens == 3
