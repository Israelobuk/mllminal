from pathlib import Path

import pytest

from mllminal.agent.provider import (
    DeterministicMilProvider,
    MilRequest,
    build_bounded_context,
    validate_plan_envelope,
)
from mllminal.contracts import Message, MessageRole, PermissionGrant
from mllminal.tools import ToolRegistry


@pytest.mark.asyncio
async def test_deterministic_provider_streams_typed_response_and_plan(tmp_path: Path) -> None:
    request = MilRequest(
        session_id="session-1",
        task_id="task-1",
        user_message="inspect this project",
        workspace_root=str(tmp_path),
        available_tools=list(ToolRegistry.definitions.values()),
        permissions=[PermissionGrant(permission="filesystem.read", workspace_root=str(tmp_path))],
    )

    events = [event async for event in DeterministicMilProvider().stream_response(request)]

    assert [event.event_type for event in events] == [
        "response.started",
        "response.delta",
        "response.completed",
        "plan.proposed",
    ]
    assert events[-1].plan is not None
    assert events[-1].plan.steps[0].proposal.tool_name == "project.inspect_metadata"


def test_validator_rejects_execution_claim_and_unknown_tool(tmp_path: Path) -> None:
    envelope = {
        "response": "I completed inspection and found files.",
        "plan": {
            "title": "Inspect",
            "steps": [
                {
                    "step_id": "one",
                    "description": "Inspect",
                    "tool": {"name": "shell.run", "arguments": {}},
                }
            ],
        },
    }

    with pytest.raises(ValueError, match="execution"):
        validate_plan_envelope(envelope, "task-1", tmp_path, ToolRegistry(), {"filesystem.read"})


def test_context_trimming_preserves_newest_messages() -> None:
    messages = [
        Message(session_id="s", role=MessageRole.USER, content=f"message-{index}")
        for index in range(5)
    ]

    trimmed, was_trimmed = build_bounded_context(messages, max_messages=2)

    assert was_trimmed is True
    assert [message.content for message in trimmed] == ["message-3", "message-4"]
