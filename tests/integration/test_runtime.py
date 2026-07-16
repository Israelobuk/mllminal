from pathlib import Path

import pytest

from mllminal.agent.provider import MilProviderEvent, MilRequest
from mllminal.agent.runtime import MilRuntime, ProviderFailure
from mllminal.contracts import ApprovalStatus, TaskState
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
