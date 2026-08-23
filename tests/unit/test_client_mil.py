import asyncio
from pathlib import Path

import httpx

from mllminal.client import mil
from mllminal.config import Settings


def test_run_mil_prompt_submits_one_prompt_through_existing_submit_path(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[tuple[object, Settings, str]] = []

    async def fake_submit(client: object, settings: Settings, content: str) -> None:
        calls.append((client, settings, content))

    monkeypatch.setattr(mil, "_submit", fake_submit)
    client = object()
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path)

    mil.run_mil_prompt(settings, "summarize this", lambda _settings: client)

    assert calls == [(client, settings, "summarize this")]


def test_run_mil_terminal_uses_terminal_native_prompt_and_exit_alias(
    tmp_path: Path, monkeypatch
) -> None:
    prompts: list[str] = []

    def fake_input(prompt: str) -> str:
        prompts.append(prompt)
        raise EOFError

    monkeypatch.setattr("builtins.input", fake_input)
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path)

    mil.run_mil_terminal(settings, lambda _settings: object())

    assert prompts == ["\u203a "]


def test_submit_recovers_when_approval_response_times_out_after_daemon_commit(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    class SlowApprovalClient:
        async def stream_chat(self, _content: str):
            yield {
                "type": "pending",
                "pending": {
                    "task": {"id": "task-1"},
                    "plan": {"steps": []},
                    "approval": {"id": "approval-1"},
                },
            }

        async def request(self, method: str, path: str, _payload=None, **_kwargs):
            if method == "POST" and path == "/v1/approvals/approval-1/decisions":
                raise httpx.ReadTimeout("approval response timed out")
            if method == "GET" and path == "/v1/tasks/task-1":
                return {"id": "task-1", "state": "COMPLETED"}
            raise AssertionError(f"unexpected request: {method} {path}")

    async def fake_prepare(_client: object, _settings: Settings) -> str:
        return "session-1"

    async def fake_history(_client: object, _session_id: str) -> list[dict[str, object]]:
        return []

    monkeypatch.setattr(mil, "_prepare_session", fake_prepare)
    monkeypatch.setattr(mil, "_history", fake_history)
    monkeypatch.setattr("builtins.input", lambda _prompt: "y")
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path)

    asyncio.run(mil._submit(SlowApprovalClient(), settings, "inspect this project"))

    output = capsys.readouterr().out
    assert "approval response timed out; checking durable task state" in output
    assert "Verified completion recorded by the daemon." in output
