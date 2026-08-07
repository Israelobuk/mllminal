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


def test_run_resolves_workflow_name_to_exact_id(tmp_path) -> None:
    calls: list[tuple[str, str, object]] = []

    class FakeClient:
        async def request(self, method, path, payload=None, *, idempotency_key=None):
            calls.append((method, path, payload))
            if path == "/v1/workflows":
                return [
                    {
                        "id": "workflow-full-id-1234",
                        "name": "Organize Downloads",
                        "state": "active",
                    }
                ]
            return {"id": "run-1", "workflow_id": "workflow-full-id-1234"}

    app = create_app(
        Settings(data_dir=tmp_path, workspace_root=tmp_path),
        daemon_client_factory=lambda _settings: FakeClient(),
    )

    result = runner.invoke(app, ["run", "Organize Downloads"])

    assert result.exit_code == 0, result.stdout
    assert calls[0][1] == "/v1/workflows"
    assert calls[1][1] == "/v1/workflows/workflow-full-id-1234/runs"


def test_run_uses_interactive_workflow_selection_when_no_id_is_given(tmp_path, monkeypatch) -> None:
    calls: list[str] = []

    class FakeClient:
        async def request(self, method, path, payload=None, *, idempotency_key=None):
            if path == "/v1/workflows":
                return [
                    {"id": "workflow-one", "name": "First workflow", "state": "active"},
                    {"id": "workflow-two", "name": "Second workflow", "state": "active"},
                ]
            calls.append(path)
            return {"id": "run-2"}

    monkeypatch.setattr(
        "mllminal.cli.terminal_commands._select_index",
        lambda items, prompt: 1,
    )
    app = create_app(
        Settings(data_dir=tmp_path, workspace_root=tmp_path),
        daemon_client_factory=lambda _settings: FakeClient(),
    )

    result = runner.invoke(app, ["run"])

    assert result.exit_code == 0, result.stdout
    assert calls == ["/v1/workflows/workflow-two/runs"]


def test_run_without_id_falls_back_to_numbered_text_in_noninteractive_mode(tmp_path) -> None:
    class FakeClient:
        async def request(self, method, path, payload=None, *, idempotency_key=None):
            assert path == "/v1/workflows"
            return [
                {"id": "workflow-one", "name": "First workflow", "state": "active"},
                {"id": "workflow-two", "name": "Second workflow", "state": "active"},
            ]

    app = create_app(
        Settings(data_dir=tmp_path, workspace_root=tmp_path),
        daemon_client_factory=lambda _settings: FakeClient(),
    )

    result = runner.invoke(app, ["run"])

    assert result.exit_code == 2
    assert "1. First workflow" in result.stdout
    assert "2. Second workflow" in result.stdout


def test_approve_resolves_pending_number_to_exact_approval_id(tmp_path) -> None:
    calls: list[str] = []

    class FakeClient:
        async def request(self, method, path, payload=None, *, idempotency_key=None):
            if path == "/v1/approvals":
                return [
                    {"id": "approval-one", "status": "PENDING", "task_id": "task-1"},
                    {"id": "approval-two", "status": "PENDING", "task_id": "task-2"},
                ]
            calls.append(path)
            return {"status": "APPROVED"}

    app = create_app(
        Settings(data_dir=tmp_path, workspace_root=tmp_path),
        daemon_client_factory=lambda _settings: FakeClient(),
    )

    result = runner.invoke(app, ["approve", "2"])

    assert result.exit_code == 0, result.stdout
    assert calls == ["/v1/approvals/approval-two/decisions"]


def test_workflows_show_friendly_short_ids_and_last_run(tmp_path) -> None:
    class FakeClient:
        async def request(self, method, path, payload=None, *, idempotency_key=None):
            if path == "/v1/workflows":
                return [
                    {
                        "id": "workflow-full-id-1234",
                        "name": "Organize Downloads",
                        "state": "active",
                    }
                ]
            if path == "/v1/workflow-runs":
                return [
                    {
                        "id": "run-1",
                        "workflow_id": "workflow-full-id-1234",
                        "state": "completed",
                        "updated_at": "2026-08-07T12:00:00Z",
                    }
                ]
            raise AssertionError(path)

    app = create_app(
        Settings(data_dir=tmp_path, workspace_root=tmp_path),
        daemon_client_factory=lambda _settings: FakeClient(),
    )

    result = runner.invoke(app, ["workflows"])

    assert result.exit_code == 0, result.stdout
    assert "Organize Downloads" in result.stdout
    assert "workflow-" in result.stdout
    assert "active" in result.stdout
    assert "completed" in result.stdout


def test_status_and_apps_use_friendly_human_output(tmp_path) -> None:
    class FakeClient:
        async def request(self, method, path, payload=None, *, idempotency_key=None):
            if path == "/v1/status":
                return {
                    "daemon": "Online",
                    "mil": "Online",
                    "provider": "qwen",
                    "model": "qwen3:4b",
                    "task_count": 2,
                }
            if path == "/v1/apps":
                return [
                    {
                        "application": "filesystem",
                        "display_name": "Windows filesystem",
                        "state": "available",
                        "available": True,
                        "metadata": {"capabilities": ["filesystem.list", "filesystem.inspect"]},
                    }
                ]
            raise AssertionError(path)

    app = create_app(
        Settings(data_dir=tmp_path, workspace_root=tmp_path),
        daemon_client_factory=lambda _settings: FakeClient(),
    )

    status = runner.invoke(app, ["status"])
    apps = runner.invoke(app, ["apps"])

    assert status.exit_code == 0, status.stdout
    assert "MLLminal is ready" in status.stdout
    assert "Daemon        Running" in status.stdout
    assert "Mil           Available" in status.stdout
    assert "Model         Qwen via Ollama" in status.stdout
    assert apps.exit_code == 0, apps.stdout
    assert "Windows filesystem" in apps.stdout
    assert "2 capabilities" in apps.stdout
