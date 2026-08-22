from pathlib import Path

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
