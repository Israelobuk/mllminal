import httpx
import pytest

from mllminal.agent.ollama import OllamaClient, OllamaProviderError


@pytest.mark.asyncio
async def test_ollama_client_streams_json_lines() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        body = (
            b'{"message":{"content":"hello"}}\n'
            b'{"message":{"content":" world"},"done":true,'
            b'"prompt_eval_count":4,"eval_count":2}\n'
        )
        return httpx.Response(200, content=body)

    client = OllamaClient("http://ollama.test", "qwen:test", transport=httpx.MockTransport(handler))
    async with client:
        chunks, usage = await client.complete([{"role": "user", "content": "hi"}])

    assert chunks == ["hello", " world"]
    assert usage == {"input_tokens": 4, "output_tokens": 2}


@pytest.mark.asyncio
async def test_ollama_client_classifies_missing_model() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model not found"})

    client = OllamaClient("http://ollama.test", "missing", transport=httpx.MockTransport(handler))
    async with client:
        with pytest.raises(OllamaProviderError, match="model_not_installed"):
            await client.complete([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_ollama_client_exposes_incremental_stream_events() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=(
                b'{"message":{"content":"first"}}\n'
                b'{"message":{"content":" second"},"done":true,"eval_count":2}\n'
            ),
        )

    client = OllamaClient("http://ollama.test", "qwen:test", transport=httpx.MockTransport(handler))
    async with client:
        events = [event async for event in client.stream_chat([{"role": "user", "content": "hi"}])]

    assert [event.text for event in events] == ["first", " second"]
    assert events[-1].done is True
    assert events[-1].usage == {"output_tokens": 2}
