import json

import httpx
from typer.testing import CliRunner

from mllminal.cli.main import create_app
from mllminal.config import Settings

runner = CliRunner()


def test_cli_exposes_terminal_first_command_groups(tmp_path) -> None:
    app = create_app(Settings(data_dir=tmp_path, workspace_root=tmp_path))

    for command in (
        "status",
        "doctor",
        "readiness",
        "version",
        "mil",
        "chat",
        "workflows",
        "executions",
        "approvals",
        "capabilities",
        "diagnostics",
        "service",
        "emergency-stop",
        "emergency-reset",
    ):
        result = runner.invoke(app, [command, "--help"])
        assert result.exit_code == 0, result.stdout


def test_status_supports_stable_json_from_authenticated_daemon(tmp_path, monkeypatch) -> None:
    class FakeClient:
        async def request(self, method, path, payload=None, *, idempotency_key=None):
            assert method == "GET"
            assert path == "/v1/status"
            return {"daemon": "Online", "task_count": 0, "schema_version": "v1"}

    app = create_app(
        Settings(data_dir=tmp_path, workspace_root=tmp_path),
        daemon_client_factory=lambda _settings: FakeClient(),
    )

    result = runner.invoke(app, ["status", "--json"])

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout) == {
        "daemon": "Online",
        "schema_version": "v1",
        "task_count": 0,
    }


def test_doctor_starts_daemon_before_reporting_health(tmp_path, monkeypatch) -> None:
    calls = []

    class FakeClient:
        async def health(self):
            return {"status": "ok"}

        async def request(self, method, path, payload=None, *, idempotency_key=None):
            assert method == "GET"
            assert path == "/v1/status"
            return {"daemon": "Online"}

    async def fake_ensure_daemon(settings, client_factory):
        calls.append(settings.data_dir)
        return {"status": "running"}

    monkeypatch.setattr("mllminal.cli.terminal_commands.ensure_daemon", fake_ensure_daemon)
    app = create_app(
        Settings(data_dir=tmp_path, workspace_root=tmp_path),
        daemon_client_factory=lambda _settings: FakeClient(),
    )

    result = runner.invoke(app, ["doctor", "--json"])

    assert result.exit_code == 0, result.stdout
    assert calls == [tmp_path]
    assert json.loads(result.stdout)["health"]["status"] == "ok"


def test_cli_version_flag_is_available_from_fresh_terminal(tmp_path) -> None:
    app = create_app(Settings(data_dir=tmp_path, workspace_root=tmp_path))

    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == "0.1.0"


def test_service_status_reports_stopped_without_daemon(tmp_path, monkeypatch) -> None:
    class FakeClient:
        async def health(self):
            raise OSError("daemon unavailable")

    monkeypatch.setattr(
        "mllminal.cli.terminal_commands.daemon_status",
        lambda _settings: {"status": "stopped"},
    )
    app = create_app(
        Settings(data_dir=tmp_path, workspace_root=tmp_path),
        daemon_client_factory=lambda _settings: FakeClient(),
    )

    result = runner.invoke(app, ["service", "status", "--json"])

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout) == {"status": "stopped"}


def test_service_status_handles_httpx_connect_error_without_traceback(
    tmp_path, monkeypatch
) -> None:
    class FakeClient:
        async def health(self):
            raise httpx.ConnectError("daemon unavailable")

    monkeypatch.setattr(
        "mllminal.cli.terminal_commands.daemon_status",
        lambda _settings: {"status": "stopped"},
    )
    app = create_app(
        Settings(data_dir=tmp_path, workspace_root=tmp_path),
        daemon_client_factory=lambda _settings: FakeClient(),
    )

    result = runner.invoke(app, ["service", "status", "--json"])

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout) == {"status": "stopped"}
    assert "Traceback" not in result.stdout


def test_service_stop_is_idempotent_when_daemon_is_stopped(tmp_path, monkeypatch) -> None:
    class FakeClient:
        async def request(self, *args, **kwargs):
            raise OSError("daemon unavailable")

    monkeypatch.setattr(
        "mllminal.cli.terminal_commands.daemon_status",
        lambda _settings: {"status": "stopped"},
    )
    app = create_app(
        Settings(data_dir=tmp_path, workspace_root=tmp_path),
        daemon_client_factory=lambda _settings: FakeClient(),
    )

    result = runner.invoke(app, ["service", "stop", "--json"])

    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout) == {"status": "already_stopped"}


def test_service_start_waits_for_bounded_readiness(tmp_path, monkeypatch) -> None:
    calls = []

    async def fake_ensure_daemon(settings, client_factory):
        calls.append(settings.data_dir)
        return {"status": "running", "health": {"status": "ok"}}

    monkeypatch.setattr("mllminal.cli.terminal_commands.ensure_daemon", fake_ensure_daemon)
    app = create_app(Settings(data_dir=tmp_path, workspace_root=tmp_path))

    result = runner.invoke(app, ["service", "start", "--json"])

    assert result.exit_code == 0, result.stdout
    assert calls == [tmp_path]
    assert json.loads(result.stdout)["health"]["status"] == "ok"


def test_service_restart_waits_for_stop_before_starting(tmp_path, monkeypatch) -> None:
    calls = []

    class FakeClient:
        async def request(self, method, path, payload=None, *, idempotency_key=None):
            assert method == "POST"
            assert path == "/v1/daemon/shutdown"
            return {"status": "stopping"}

        async def health(self):
            raise OSError("daemon stopped")

    async def fake_ensure_daemon(settings, client_factory):
        calls.append(settings.data_dir)
        return {"status": "running", "started": {"pid": 123}}

    monkeypatch.setattr("mllminal.cli.terminal_commands.ensure_daemon", fake_ensure_daemon)
    app = create_app(
        Settings(data_dir=tmp_path, workspace_root=tmp_path),
        daemon_client_factory=lambda _settings: FakeClient(),
    )

    result = runner.invoke(app, ["service", "restart", "--json"])

    assert result.exit_code == 0, result.stdout
    assert calls == [tmp_path]
    assert json.loads(result.stdout)["status"] == "running"


def test_cli_exposes_simple_common_commands(tmp_path) -> None:
    app = create_app(Settings(data_dir=tmp_path, workspace_root=tmp_path))

    for command in (
        "help",
        "run",
        "apps",
        "flows",
        "runs",
        "approve",
        "deny",
        "stop",
        "start",
    ):
        result = runner.invoke(app, [command, "--help"])
        assert result.exit_code == 0, result.stdout


def test_cli_help_prioritizes_normal_user_actions(tmp_path) -> None:
    app = create_app(Settings(data_dir=tmp_path, workspace_root=tmp_path))

    result = runner.invoke(app, ["help"])

    assert result.exit_code == 0, result.stdout
    assert "MLLminal - local workflow intelligence" in result.stdout
    assert "mllminal              Open Mil" in result.stdout
    assert "mllminal run          Run a workflow" in result.stdout
    assert "Advanced commands:" in result.stdout
    assert result.stdout.index("Common commands:") < result.stdout.index("Advanced commands:")


def test_cli_root_and_chat_open_the_same_mil_terminal(tmp_path, monkeypatch) -> None:
    calls: list[str] = []

    async def fake_ensure_daemon(settings, client_factory):
        calls.append("ensure")
        return {"status": "running"}

    def fake_mil_terminal(settings, client_factory) -> None:
        calls.append("mil")

    monkeypatch.setattr("mllminal.cli.terminal_commands.ensure_daemon", fake_ensure_daemon)
    monkeypatch.setattr("mllminal.client.mil.run_mil_terminal", fake_mil_terminal)
    app = create_app(Settings(data_dir=tmp_path, workspace_root=tmp_path))

    for args in ([], ["chat"], ["mil"]):
        calls.clear()
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.stdout
        assert calls == ["ensure", "mil"]
