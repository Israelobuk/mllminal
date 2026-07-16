"""Dedicated async client for an Ollama-compatible local model server."""

import json
from typing import Any

import httpx


class OllamaProviderError(RuntimeError):
    def __init__(self, category: str, message: str, retryable: bool = False) -> None:
        super().__init__(f"{category}: {message}")
        self.category = category
        self.retryable = retryable


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

    async def complete(self, messages: list[dict[str, str]]) -> tuple[list[str], dict[str, int]]:
        try:
            response = await self._client.post(
                "/api/chat", json={"model": self.model, "messages": messages, "stream": True}
            )
        except httpx.TimeoutException as error:
            raise OllamaProviderError("timeout", "Local model request timed out", True) from error
        except httpx.HTTPError as error:
            raise OllamaProviderError(
                "unavailable", "Local model server is unavailable", True
            ) from error
        if response.status_code == 404:
            raise OllamaProviderError("model_not_installed", "Configured model is not installed")
        if response.status_code >= 400:
            raise OllamaProviderError(
                "http_error", f"Model server returned {response.status_code}", True
            )
        chunks: list[str] = []
        usage: dict[str, int] = {}
        for line in response.text.splitlines():
            try:
                item: dict[str, Any] = json.loads(line)
            except json.JSONDecodeError as error:
                raise OllamaProviderError(
                    "malformed_response", "Model server returned invalid JSON"
                ) from error
            message = item.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                chunks.append(message["content"])
            if isinstance(item.get("prompt_eval_count"), int):
                usage["input_tokens"] = item["prompt_eval_count"]
            if isinstance(item.get("eval_count"), int):
                usage["output_tokens"] = item["eval_count"]
        return chunks, usage
