import json
from pathlib import Path

import httpx
import pytest

from mllminal.agent.ollama import OllamaClient, OllamaStreamEvent
from mllminal.agent.provider import MilRequest, QwenMilProvider
from mllminal.agent.prompts import conversation_message


class StreamingOllamaClient:
    def __init__(self) -> None:
        self.requests: list[list[dict[str, str]]] = []

    async def stream_chat(self, messages: list[dict[str, str]]):
        self.requests.append(messages)
        yield OllamaStreamEvent(text="Hello", done=False, usage={})
        yield OllamaStreamEvent(
            text=" from Mil.",
            done=True,
            usage={"input_tokens": 4, "output_tokens": 3},
        )


@pytest.mark.asyncio
async def test_qwen_conversation_emits_each_streamed_chunk(tmp_path: Path) -> None:
    client = StreamingOllamaClient()
    request = MilRequest(
        session_id="session-1",
        task_id=None,
        user_message="hello",
        workspace_root=str(tmp_path),
    )

    events = [event async for event in QwenMilProvider(client).stream_conversation(request)]

    assert [event.event_type for event in events] == [
        "response.started",
        "response.delta",
        "response.delta",
        "response.completed",
    ]
    assert [event.text for event in events[1:3]] == ["Hello", " from Mil."]
    assert events[-1].detail == {"input_tokens": 4, "output_tokens": 3}
    assert client.requests[0][0] == {"role": "system", "content": conversation_message()}


@pytest.mark.asyncio
async def test_ollama_client_sends_keep_alive_for_warm_conversation_requests() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["keep_alive"] == "15m"
        return httpx.Response(
            200,
            content=b'{"message":{"content":"ready"},"done":true}\n',
        )

    client = OllamaClient(
        "http://ollama.test",
        "qwen:test",
        keep_alive="15m",
        transport=httpx.MockTransport(handler),
    )
    async with client:
        events = [event async for event in client.stream_chat([{"role": "user", "content": "hi"}])]

    assert events[0].text == "ready"
