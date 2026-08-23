from pathlib import Path

from mllminal.client.interactive.session import InteractiveSession
from mllminal.config import Settings


class FakeInteractiveClient:
    def __init__(self, _settings: Settings) -> None:
        self.session_id: str | None = None

    async def request(self, _method: str, path: str, *_args: object, **_kwargs: object):
        values = {
            "/v1/status": {"daemon": "Online", "model": "qwen3:4b", "provider": "qwen"},
            "/v1/tasks": [],
            "/v1/workflows": [],
            "/v1/workflow-runs": [],
            "/v1/apps": [],
            "/v1/approvals": [],
        }
        return values.get(path, {})

    async def health(self) -> dict[str, str]:
        return {"status": "ok", "daemon": "mllminald"}


def test_session_renders_startup_and_product_commands_without_a_tty(tmp_path: Path) -> None:
    inputs = iter(["/help", "/status", "/exit"])
    output: list[str] = []
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path)

    InteractiveSession(
        settings,
        FakeInteractiveClient,
        input_func=lambda _prompt: next(inputs),
        output=output.append,
        width=42,
        no_color=True,
        use_prompt_toolkit=False,
    ).run()

    rendered = "\n".join(output)
    assert "MLLminal" in rendered
    assert "/workflows" in rendered
    assert "Runtime          Ready" in rendered
    assert output[-1] == "Session ended."


def test_session_multiline_mode_is_predictable_and_does_not_kill_daemon(tmp_path: Path) -> None:
    inputs = iter(["/begin", "summarize", "these files", "/end", "/exit"])
    submitted: list[str] = []
    settings = Settings(data_dir=tmp_path / "data", workspace_root=tmp_path)
    session = InteractiveSession(
        settings,
        FakeInteractiveClient,
        input_func=lambda _prompt: next(inputs),
        output=lambda _value: None,
        width=42,
        no_color=True,
        use_prompt_toolkit=False,
    )
    session._submit = submitted.append

    session.run()

    assert submitted == ["summarize\nthese files"]
