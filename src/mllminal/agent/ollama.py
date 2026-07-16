"""Dedicated async client for an Ollama-compatible local model server."""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx


class OllamaProviderError(RuntimeError):
    def __init__(self, category: str, message: str, retryable: bool = False) -> None:
        super().__init__(f"{category}: {message}")
        self.category = category
        self.retryable = retryable


@dataclass(frozen=True)
class OllamaStreamEvent:
    text: str
    done: bool
    usage: dict[str, int]


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout_seconds: float = 120,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds),
            transport=transport,
        )

    async def __aenter__(self) -> "OllamaClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def model_available(self) -> bool:
        """Return whether the configured model appears in the local model registry."""
        try:
            response = await self._client.get("/api/tags")
        except httpx.TimeoutException as error:
            raise OllamaProviderError("timeout", "Local model request timed out", True) from error
        except httpx.HTTPError as error:
            raise OllamaProviderError(
                "unavailable", "Local model server is unavailable", True
            ) from error
        self._raise_for_status(response)
        try:
            payload: object = response.json()
        except json.JSONDecodeError as error:
            raise OllamaProviderError(
                "malformed_response", "Model server returned invalid JSON"
            ) from error
        if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
            raise OllamaProviderError("malformed_response", "Model registry response is invalid")
        return any(
            isinstance(item, dict) and item.get("name") == self.model for item in payload["models"]
        )

    async def stream_chat(self, messages: list[dict[str, str]]) -> AsyncIterator[OllamaStreamEvent]:
        try:
            async with self._client.stream(
                "POST",
                "/api/chat",
                json={"model": self.model, "messages": messages, "stream": True},
            ) as response:
                self._raise_for_status(response)
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    yield self._parse_line(line)
        except httpx.TimeoutException as error:
            raise OllamaProviderError("timeout", "Local model request timed out", True) from error
        except httpx.HTTPError as error:
            raise OllamaProviderError(
                "unavailable", "Local model server is unavailable", True
            ) from error

    async def complete(self, messages: list[dict[str, str]]) -> tuple[list[str], dict[str, int]]:
        chunks: list[str] = []
        usage: dict[str, int] = {}
        async for event in self.stream_chat(messages):
            if event.text:
                chunks.append(event.text)
            usage.update(event.usage)
        return chunks, usage

    @staticmethod
    def _parse_line(line: str) -> OllamaStreamEvent:
        try:
            item: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError as error:
            raise OllamaProviderError(
                "malformed_response", "Model server returned invalid JSON"
            ) from error
        message = item.get("message")
        text = message.get("content", "") if isinstance(message, dict) else ""
        if not isinstance(text, str):
            raise OllamaProviderError("malformed_response", "Model response content is invalid")
        usage: dict[str, int] = {}
        if isinstance(item.get("prompt_eval_count"), int):
            usage["input_tokens"] = item["prompt_eval_count"]
        if isinstance(item.get("eval_count"), int):
            usage["output_tokens"] = item["eval_count"]
        return OllamaStreamEvent(text=text, done=item.get("done") is True, usage=usage)

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code == 404:
            raise OllamaProviderError("model_not_installed", "Configured model is not installed")
        if response.status_code >= 400:
            raise OllamaProviderError(
                "http_error", f"Model server returned {response.status_code}", True
            )
