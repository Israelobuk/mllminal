import json

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
