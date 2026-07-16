from pathlib import Path

import pytest

from mllminal.agent.prompts import system_message
from mllminal.agent.provider import MilRequest, QwenMilProvider
from mllminal.contracts import PermissionGrant
from mllminal.tools import ToolRegistry


class FakeOllamaClient:
    def __init__(self, responses: list[tuple[list[str], dict[str, int]]]) -> None:
        self.responses = responses
        self.requests: list[list[dict[str, str]]] = []

    async def complete(self, messages: list[dict[str, str]]) -> tuple[list[str], dict[str, int]]:
        self.requests.append(messages)
        return self.responses.pop(0)


@pytest.mark.asyncio
async def test_qwen_provider_validates_ollama_envelope_before_proposing_plan(
    tmp_path: Path,
) -> None:
    client = FakeOllamaClient(
        [
            (
                [
                    '{"response":"I can inspect metadata after approval.",',
                    '"plan":{"title":"Inspect","steps":[{"step_id":"inspect",',
                    '"description":"Inspect metadata","tool":{"name":',
                    '"project.inspect_metadata","arguments":{}}}]}}',
                ],
                {"input_tokens": 5, "output_tokens": 7},
            )
        ]
    )
    request = MilRequest(
        session_id="session-1",
        task_id="task-1",
        user_message="inspect this project",
        workspace_root=str(tmp_path),
        available_tools=list(ToolRegistry.definitions.values()),
        permissions=[PermissionGrant(permission="filesystem.read", workspace_root=str(tmp_path))],
    )

    events = [event async for event in QwenMilProvider(client).stream_response(request)]

    assert [event.event_type for event in events] == [
        "response.started",
        "response.delta",
        "response.completed",
        "plan.proposed",
    ]
    assert events[1].text == "I can inspect metadata after approval."
    assert events[-1].plan is not None
    assert events[-1].plan.steps[0].proposal.tool_name == "project.inspect_metadata"
    assert events[-1].detail == {"input_tokens": 5, "output_tokens": 7}
    assert client.requests[0][0] == {"role": "system", "content": system_message()}
    assert client.requests[0][-1] == {"role": "user", "content": "inspect this project"}


@pytest.mark.asyncio
async def test_qwen_provider_repairs_one_invalid_envelope_before_proposing(tmp_path: Path) -> None:
    client = FakeOllamaClient(
        [
            (
                [
                    '{"response":"I can inspect.","plan":{"title":"Inspect",',
                    '"steps":[{"step_id":"bad","description":"Run shell",',
                    '"tool":{"name":"shell.run","arguments":{}}}]}}',
                ],
                {},
            ),
            (
                [
                    '{"response":"I can inspect metadata after approval.",',
                    '"plan":{"title":"Inspect","steps":[{"step_id":"inspect",',
                    '"description":"Inspect metadata","tool":{"name":',
                    '"project.inspect_metadata","arguments":{}}}]}}',
                ],
                {},
            ),
        ]
    )
    request = MilRequest(
        session_id="session-1",
        task_id="task-1",
        user_message="inspect this project",
        workspace_root=str(tmp_path),
        available_tools=list(ToolRegistry.definitions.values()),
        permissions=[PermissionGrant(permission="filesystem.read", workspace_root=str(tmp_path))],
    )

    events = [event async for event in QwenMilProvider(client).stream_response(request)]

    assert events[-1].event_type == "plan.proposed"
    assert len(client.requests) == 2
    assert "repair" in client.requests[1][-1]["content"].lower()
