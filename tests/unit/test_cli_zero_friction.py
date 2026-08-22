from pathlib import Path

from typer.testing import CliRunner

from mllminal.cli.main import create_app
from mllminal.config import Settings

runner = CliRunner()


def test_root_prompt_uses_one_shot_mode_and_shared_bootstrap(tmp_path: Path, monkeypatch) -> None:
    calls: list[tuple[str, Path | None, str | None]] = []

    async def fake_ensure(settings: Settings, _factory: object) -> dict[str, object]:
        calls.append(("ensure", settings.workspace_root, None))
        return {"status": "running", "health": {"status": "ok"}}

    def fake_prompt(settings: Settings, prompt: str, _factory: object) -> None:
        calls.append(("prompt", settings.workspace_root, prompt))

    monkeypatch.setattr("mllminal.cli.terminal_commands.ensure_daemon", fake_ensure)
    monkeypatch.setattr("mllminal.client.mil.run_mil_prompt", fake_prompt)
    app = create_app(
        Settings(data_dir=tmp_path / "data", workspace_root=tmp_path),
        daemon_client_factory=lambda _settings: object(),
    )

    result = runner.invoke(app, ["summarize the files"])

    assert result.exit_code == 0, result.stdout
    assert calls == [
        ("ensure", tmp_path, None),
        ("prompt", tmp_path, "summarize the files"),
    ]
    assert "Mil is ready." in result.stdout


def test_root_workspace_mode_normalizes_path_and_opens_interactive_mil(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    calls: list[tuple[str, Path]] = []

    async def fake_ensure(settings: Settings, _factory: object) -> dict[str, object]:
        calls.append(("ensure", settings.workspace_root))
        return {"status": "running", "health": {"status": "ok"}}

    def fake_terminal(settings: Settings, _factory: object) -> None:
        calls.append(("terminal", settings.workspace_root))

    monkeypatch.setattr("mllminal.cli.terminal_commands.ensure_daemon", fake_ensure)
    monkeypatch.setattr("mllminal.client.mil.run_mil_terminal", fake_terminal)
    app = create_app(
        Settings(data_dir=tmp_path / "data", workspace_root=tmp_path),
        daemon_client_factory=lambda _settings: object(),
    )

    result = runner.invoke(app, [str(workspace / ".")])

    assert result.exit_code == 0, result.stdout
    assert calls == [("ensure", workspace.resolve()), ("terminal", workspace.resolve())]
    assert f"Workspace: {workspace.resolve()}" in result.stdout


def test_root_rejects_missing_path_like_target_without_starting_daemon(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "mllminal.cli.terminal_commands.ensure_daemon",
        lambda *_args: calls.append("ensure"),
    )
    app = create_app(Settings(data_dir=tmp_path / "data", workspace_root=tmp_path))

    result = runner.invoke(app, [str(tmp_path / "missing-folder")])

    assert result.exit_code == 2
    assert "workspace does not exist" in result.output


def test_service_dependent_groups_share_runtime_bootstrap(tmp_path: Path, monkeypatch) -> None:
    calls: list[Path] = []

    class FakeClient:
        async def health(self) -> dict[str, str]:
            return {"status": "ok"}

        async def request(self, method, path, payload=None, *, idempotency_key=None):
            del method, payload, idempotency_key
            if path == "/v1/workflows":
                return []
            if path == "/v1/apps":
                return []
            if path == "/v1/approvals":
                return []
            raise AssertionError(path)

    async def fake_ensure(settings: Settings, _factory: object) -> dict[str, object]:
        calls.append(settings.workspace_root)
        return {"status": "running", "health": {"status": "ok"}}

    monkeypatch.setattr("mllminal.cli.terminal_commands.ensure_daemon", fake_ensure)
    monkeypatch.setattr("mllminal.cli.main.ensure_daemon", fake_ensure)
    app = create_app(
        Settings(data_dir=tmp_path / "data", workspace_root=tmp_path),
        daemon_client_factory=lambda _settings: FakeClient(),
    )

    for args in (
        ["workflows", "list"],
        ["applications", "list"],
        ["approvals", "list"],
        ["apps"],
    ):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.output

    assert calls == [tmp_path, tmp_path, tmp_path, tmp_path]


def test_help_groups_start_common_safety_and_advanced_commands(tmp_path: Path) -> None:
    app = create_app(Settings(data_dir=tmp_path / "data", workspace_root=tmp_path))

    result = runner.invoke(app, ["help"])

    assert result.exit_code == 0, result.output
    assert "Start" in result.output
    assert "mllminal              Start Mil" in result.output
    assert 'mllminal "<prompt>"' in result.output
    assert "Safety and approvals" in result.output
    assert "Advanced" in result.output
    assert result.output.index("Start") < result.output.index("Advanced")


def test_doctor_repair_reports_requested_lifecycle_repair(tmp_path: Path, monkeypatch) -> None:
    class FakeClient:
        async def health(self) -> dict[str, str]:
            return {"status": "ok"}

        async def request(self, method, path, payload=None, *, idempotency_key=None):
            del method, payload, idempotency_key
            assert path == "/v1/status"
            return {"daemon": "Online"}

    async def fake_ensure(settings: Settings, _factory: object) -> dict[str, object]:
        return {"status": "running", "health": {"status": "ok"}}

    monkeypatch.setattr("mllminal.cli.terminal_commands.ensure_daemon", fake_ensure)
    monkeypatch.setattr(
        "mllminal.cli.terminal_commands.daemon_status",
        lambda _settings: {"status": "stopped"},
    )
    app = create_app(
        Settings(data_dir=tmp_path / "data", workspace_root=tmp_path),
        daemon_client_factory=lambda _settings: FakeClient(),
    )

    result = runner.invoke(app, ["doctor", "--repair", "--json"])

    assert result.exit_code == 0, result.output
    assert '"requested": true' in result.output
