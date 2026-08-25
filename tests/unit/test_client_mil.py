import asyncio
from pathlib import Path

import httpx
import pytest

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

    assert prompts == ["> "]


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


def test_submit_reports_closed_local_stream(tmp_path: Path, monkeypatch) -> None:
    class BrokenStreamClient:
        async def stream_chat(self, _content: str):
            raise httpx.ReadError("connection closed")
            yield {}

    async def fake_prepare(_client: object, _settings: Settings) -> str:
        return "session-1"

    monkeypatch.setattr(mil, "_prepare_session", fake_prepare)
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path)

    with pytest.raises(RuntimeError, match="Mil stream closed before completion"):
        asyncio.run(mil._submit(BrokenStreamClient(), settings, "inspect this project"))


def test_submit_renders_fast_chat_without_waiting_for_a_pending_task(
    tmp_path: Path, capsys
) -> None:
    class ChatClient:
        async def stream_chat(self, _content: str):
            yield {
                "type": "event",
                "event": {
                    "event_type": "response.delta",
                    "payload": {"text": "Hello from Mil."},
                },
            }
            yield {"type": "chat", "response": "Hello from Mil.", "cached": True}

    async def fake_prepare(_client: object, _settings: Settings) -> str:
        return "session-1"

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(mil, "_prepare_session", fake_prepare)
    try:
        settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path)
        asyncio.run(mil._submit(ChatClient(), settings, "hi"))
    finally:
        monkeypatch.undo()

    assert capsys.readouterr().out == "Hello from Mil.\n"


def test_submit_accepts_interactive_output_and_input_surfaces(tmp_path: Path, capsys) -> None:
    events: list[str] = []

    class InteractiveClient:
        async def stream_chat(self, _content: str):
            yield {
                "type": "event",
                "event": {
                    "event_type": "response.delta",
                    "payload": {"text": "Thinking"},
                },
            }
            yield {
                "type": "pending",
                "pending": {
                    "task": {"id": "task-1"},
                    "plan": {"steps": [{"position": 1, "title": "Open project"}]},
                    "approval": {"id": "approval-1"},
                },
            }

        async def request(self, method: str, path: str, _payload=None, **_kwargs):
            if method == "POST" and path == "/v1/approvals/approval-1/decisions":
                return {"state": "APPROVED"}
            if method == "GET" and path == "/v1/tasks/task-1":
                return {"id": "task-1", "state": "COMPLETED"}
            raise AssertionError(f"unexpected request: {method} {path}")

    async def fake_prepare(_client: object, _settings: Settings) -> str:
        return "session-1"

    async def fake_history(_client: object, _session_id: str) -> list[dict[str, object]]:
        return []

    async def read(prompt: str) -> str:
        events.append(prompt)
        return "approve"

    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path)
    original_prepare = mil._prepare_session
    original_history = mil._history
    mil._prepare_session = fake_prepare
    mil._history = fake_history
    try:
        asyncio.run(
            mil._submit(
                InteractiveClient(),
                settings,
                "inspect this project",
                output=events.append,
                input_func=read,
                stream_output=lambda value: events.append(f"stream:{value}"),
                response_started=lambda: events.append("Mil"),
                approval_prompt="approval surface",
                plan_renderer=lambda steps: f"PLAN CARD {steps[0]}",
                state_renderer=lambda state: f"STATE CARD {state}",
                result_renderer=lambda state: f"RESULT CARD {state}",
            )
        )
    finally:
        mil._prepare_session = original_prepare
        mil._history = original_history

    assert capsys.readouterr().out == ""
    assert events == [
        "Mil",
        "stream:Thinking",
        "",
        "PLAN CARD Open project",
        "approval surface",
        "approval: APPROVED",
        "STATE CARD COMPLETED",
        "RESULT CARD COMPLETED",
    ]


def test_wait_for_final_retries_after_transient_task_status_timeout(monkeypatch) -> None:
    class FlakyTaskClient:
        def __init__(self) -> None:
            self.calls = 0

        async def request(self, method: str, path: str):
            assert method == "GET"
            assert path == "/v1/tasks/task-1"
            self.calls += 1
            if self.calls == 1:
                raise httpx.ReadTimeout("task status response timed out")
            return {"id": "task-1", "state": "COMPLETED"}

    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr(mil.asyncio, "sleep", no_wait)

    client = FlakyTaskClient()
    result = asyncio.run(mil._wait_for_final(client, "task-1"))

    assert result["state"] == "COMPLETED"
    assert client.calls == 2


def test_prepare_session_discards_missing_persisted_session(tmp_path: Path) -> None:
    class StaleSessionClient:
        def __init__(self) -> None:
            self.session_id: str | None = None

        async def request(self, method: str, path: str) -> object:
            assert method == "GET"
            assert path.startswith("/v1/sessions/")
            request = httpx.Request("GET", "http://mllminal.test" + path)
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError("missing", request=request, response=response)

        async def ensure_session(self) -> str:
            assert self.session_id is None
            self.session_id = "new-session"
            return self.session_id

    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path)
    settings.ensure_data_dir()
    (settings.data_dir / "mil-session").write_text("stale-session\n", encoding="utf-8")
    client = StaleSessionClient()

    session_id = asyncio.run(mil._prepare_session(client, settings))

    assert session_id == "new-session"
    assert (settings.data_dir / "mil-session").read_text(encoding="utf-8").strip() == "new-session"
