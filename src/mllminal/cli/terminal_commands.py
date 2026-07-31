"""Daemon-backed, terminal-first command projections.

The historical singular command groups remain available for compatibility.  This
module adds the stable user-facing names from the CLI product contract and keeps
all live state behind the authenticated daemon client.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer

from mllminal.client.api import DaemonClient
from mllminal.config import Settings
from mllminal.install_lifecycle import InstallLifecycle, InstallLifecycleError
from mllminal.service_lifecycle import ensure_daemon

ClientFactory = Callable[[Settings], DaemonClient]


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _human(value: object) -> str:
    if isinstance(value, dict):
        return "\n".join(f"{key}: {value[key]}" for key in sorted(value))
    if isinstance(value, list):
        return "\n".join(_human(item) if isinstance(item, dict) else str(item) for item in value)
    return str(value)


def _emit(value: object, json_output: bool) -> None:
    typer.echo(_json(value) if json_output else _human(value))


def _request(
    settings: Settings,
    factory: ClientFactory,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    idempotency_key: str | None = None,
) -> object:
    try:
        return asyncio.run(
            factory(settings).request(method, path, payload, idempotency_key=idempotency_key)
        )
    except PermissionError as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=2) from None
    except (OSError, RuntimeError, TimeoutError) as error:
        typer.echo(f"Error: {error}", err=True)
        raise typer.Exit(code=3) from None


def _stream_workflow(
    settings: Settings, factory: ClientFactory, run_id: str, json_output: bool
) -> None:
    async def stream() -> None:
        sequence = 0
        async for event in factory(settings).stream_workflow_events(run_id, sequence):
            if isinstance(event, dict):
                sequence = max(sequence, int(event.get("sequence", sequence)))
            typer.echo(_json(event) if json_output else _human(event))

    try:
        asyncio.run(stream())
    except (OSError, RuntimeError, TimeoutError) as error:
        typer.echo(f"Error: event stream unavailable: {error}", err=True)
        raise typer.Exit(code=3) from None


def _daemon_executable(settings: Settings) -> str | None:
    candidates = [
        shutil.which("mllminald"),
        str(settings.data_dir.parent / "app" / "runtime" / "Scripts" / "mllminald.exe"),
        str(Path(sys.executable).with_name("mllminald.exe")),
    ]
    return next((item for item in candidates if item and Path(item).is_file()), None)


def _start_daemon(settings: Settings) -> dict[str, Any]:
    executable = _daemon_executable(settings)
    if executable is None:
        raise RuntimeError("installed mllminald executable was not found")
    flags = 0
    if sys.platform == "win32":
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )
    process = subprocess.Popen(
        [executable],
        cwd=str(settings.workspace_root),
        creationflags=flags,
        close_fds=True,
    )
    return {"status": "starting", "pid": process.pid}


def register_terminal_commands(
    app: typer.Typer,
    settings: Settings,
    *,
    daemon_client_factory: ClientFactory = DaemonClient,
) -> None:
    """Register stable CLI projections without moving authority out of the daemon."""

    workflows = typer.Typer(help="Inspect and run daemon-owned workflows.")
    executions = typer.Typer(help="Inspect and control durable workflow executions.")
    approvals = typer.Typer(help="Review exact daemon-owned approval requests.")
    applications = typer.Typer(help="Discover bounded application surfaces.")
    capabilities = typer.Typer(help="Inspect bounded, typed capabilities.")
    diagnostics = typer.Typer(help="Collect and verify safe diagnostic projections.")
    service = typer.Typer(help="Control the local MLLminal daemon service.")
    install = typer.Typer(help="Install, repair, and safely remove MLLminal-owned state.")

    @app.callback(invoke_without_command=True)
    def root_options(
        version: bool = typer.Option(
            False, "--version", help="Print the installed MLLminal version."
        ),
    ) -> None:
        if version:
            try:
                value = importlib.metadata.version("mllminal")
            except importlib.metadata.PackageNotFoundError:
                value = "0.1.0"
            typer.echo(value)
            raise typer.Exit()

    def lifecycle() -> InstallLifecycle:
        return InstallLifecycle(settings)

    def lifecycle_emit(action: Callable[[], object], json_output: bool) -> None:
        try:
            _emit(action(), json_output)
        except InstallLifecycleError as error:
            typer.echo(f"Error: {error}", err=True)
            raise typer.Exit(code=2) from None
        except (OSError, RuntimeError) as error:
            typer.echo(f"Error: {error}", err=True)
            raise typer.Exit(code=3) from None

    @install.command("status")
    def install_status(json_output: bool = typer.Option(False, "--json")) -> None:
        lifecycle_emit(lifecycle().status, json_output)

    @install.command("repair")
    def install_repair(json_output: bool = typer.Option(False, "--json")) -> None:
        lifecycle_emit(lifecycle().repair, json_output)

    @install.command("data-path")
    def install_data_path(json_output: bool = typer.Option(False, "--json")) -> None:
        lifecycle_emit(lifecycle().data_path, json_output)

    @install.command("purge-data")
    def install_purge_data(
        confirm: str | None = typer.Option(None, "--confirm"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        lifecycle_emit(lambda: lifecycle().purge(confirm), json_output)

    @app.command("tui")
    def tui() -> None:
        from mllminal.client.app import main as run_tui

        run_tui()

    @app.command("status")
    def status(json_output: bool = typer.Option(False, "--json")) -> None:
        _emit(_request(settings, daemon_client_factory, "GET", "/v1/status"), json_output)

    @app.command("doctor")
    def doctor(json_output: bool = typer.Option(False, "--json")) -> None:
        async def check() -> dict[str, Any]:
            client = daemon_client_factory(settings)
            health = await client.health()
            status_value = await client.request("GET", "/v1/status")
            return {"health": health, "status": status_value}

        try:
            _emit(asyncio.run(check()), json_output)
        except (OSError, PermissionError, RuntimeError, TimeoutError) as error:
            typer.echo(f"Error: {error}", err=True)
            raise typer.Exit(code=3) from None

    @app.command("readiness")
    def readiness(json_output: bool = typer.Option(False, "--json")) -> None:
        status_value = _request(settings, daemon_client_factory, "GET", "/v1/status")
        ready = isinstance(status_value, dict) and status_value.get("daemon") == "Online"
        _emit(
            {"ready": ready, "reason": "daemon_online" if ready else "daemon_unavailable"},
            json_output,
        )
        if not ready:
            raise typer.Exit(code=3)

    @app.command("version")
    def version(json_output: bool = typer.Option(False, "--json")) -> None:
        try:
            package_version = importlib.metadata.version("mllminal")
        except importlib.metadata.PackageNotFoundError:
            package_version = "0.1.0"
        _emit(
            {
                "name": "mllminal",
                "version": package_version,
                "python": sys.version.split()[0],
                "platform": platform.platform(),
            },
            json_output,
        )

    @app.command("emergency-stop")
    def emergency_stop(json_output: bool = typer.Option(False, "--json")) -> None:
        _emit(
            _request(
                settings,
                daemon_client_factory,
                "POST",
                "/v1/privacy/emergency-stop",
                idempotency_key="cli-emergency-stop",
            ),
            json_output,
        )

    @app.command("emergency-reset")
    def emergency_reset(json_output: bool = typer.Option(False, "--json")) -> None:
        _emit(
            _request(
                settings,
                daemon_client_factory,
                "POST",
                "/v1/privacy/emergency-clear",
                idempotency_key="cli-emergency-reset",
            ),
            json_output,
        )

    @app.command("chat")
    def chat(
        message: str | None = typer.Option(None, "--message", "-m"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        if message is None:
            typer.echo("Use 'mllminal mil' for the interactive terminal, or pass --message.")
            return
        try:
            result = asyncio.run(daemon_client_factory(settings).chat(message))
        except (OSError, PermissionError, RuntimeError, TimeoutError) as error:
            typer.echo(f"Error: {error}", err=True)
            raise typer.Exit(code=3) from None
        _emit(result, json_output)

    @app.command("mil")
    def mil(
        message: str | None = typer.Option(None, "--message", "-m"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        """Run Mil interactively, or submit one durable message."""
        if message is not None:
            chat(message=message, json_output=json_output)
            return
        from mllminal.client.mil import run_mil_terminal

        try:
            asyncio.run(ensure_daemon(settings, daemon_client_factory))
        except (OSError, RuntimeError, TimeoutError) as error:
            typer.echo(f"Error: {error}", err=True)
            raise typer.Exit(code=3) from None
        run_mil_terminal(settings, daemon_client_factory)

    @workflows.command("list")
    def workflows_list(json_output: bool = typer.Option(False, "--json")) -> None:
        _emit(_request(settings, daemon_client_factory, "GET", "/v1/workflows"), json_output)

    @workflows.command("show")
    def workflows_show(workflow_id: str, json_output: bool = typer.Option(False, "--json")) -> None:
        _emit(
            _request(settings, daemon_client_factory, "GET", f"/v1/workflows/{workflow_id}"),
            json_output,
        )

    @workflows.command("propose")
    def workflows_propose(payload: str, json_output: bool = typer.Option(False, "--json")) -> None:
        try:
            body = json.loads(payload)
        except json.JSONDecodeError as error:
            typer.echo(f"Error: invalid proposal JSON: {error.msg}", err=True)
            raise typer.Exit(code=2) from None
        _emit(
            _request(
                settings, daemon_client_factory, "POST", "/v1/workflow-compiler/compile", body
            ),
            json_output,
        )

    @workflows.command("validate")
    def workflows_validate(
        workflow_id: str, json_output: bool = typer.Option(False, "--json")
    ) -> None:
        value = _request(settings, daemon_client_factory, "GET", f"/v1/workflows/{workflow_id}")
        _emit({"workflow_id": workflow_id, "valid": True, "definition": value}, json_output)

    @workflows.command("run")
    def workflows_run(
        workflow_id: str,
        inputs: str = typer.Option("{}", "--inputs"),
        live: bool = typer.Option(False, "--live"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        try:
            body = {"inputs": json.loads(inputs), "preview": not live}
        except json.JSONDecodeError as error:
            typer.echo(f"Error: invalid inputs JSON: {error.msg}", err=True)
            raise typer.Exit(code=2) from None
        _emit(
            _request(
                settings,
                daemon_client_factory,
                "POST",
                f"/v1/workflows/{workflow_id}/runs",
                body,
                idempotency_key=f"cli-workflow-run-{workflow_id}",
            ),
            json_output,
        )

    @executions.command("list")
    def executions_list(json_output: bool = typer.Option(False, "--json")) -> None:
        _emit(_request(settings, daemon_client_factory, "GET", "/v1/workflow-runs"), json_output)

    @executions.command("show")
    def executions_show(
        execution_id: str, json_output: bool = typer.Option(False, "--json")
    ) -> None:
        _emit(
            _request(
                settings,
                daemon_client_factory,
                "GET",
                f"/v1/workflow-runs/{execution_id}/execution",
            ),
            json_output,
        )

    @executions.command("watch")
    def executions_watch(
        execution_id: str, json_output: bool = typer.Option(False, "--json")
    ) -> None:
        _stream_workflow(settings, daemon_client_factory, execution_id, json_output)

    @executions.command("pause")
    def executions_pause(
        execution_id: str, json_output: bool = typer.Option(False, "--json")
    ) -> None:
        value = _request(
            settings,
            daemon_client_factory,
            "GET",
            f"/v1/workflow-runs/{execution_id}/execution",
        )
        if isinstance(value, dict) and value.get("state") == "paused":
            _emit(value, json_output)
            return
        typer.echo(
            "Error: this execution has no resumable paused state; "
            "use an explicit approval or cancel.",
            err=True,
        )
        raise typer.Exit(code=2)

    @executions.command("cancel")
    def executions_cancel(
        execution_id: str, json_output: bool = typer.Option(False, "--json")
    ) -> None:
        _emit(
            _request(
                settings,
                daemon_client_factory,
                "POST",
                f"/v1/workflow-runs/{execution_id}/cancel",
                idempotency_key=f"cli-execution-cancel-{execution_id}",
            ),
            json_output,
        )

    @executions.command("resume")
    def executions_resume(
        execution_id: str, json_output: bool = typer.Option(False, "--json")
    ) -> None:
        _emit(
            _request(
                settings,
                daemon_client_factory,
                "POST",
                f"/v1/workflow-runs/{execution_id}/resume",
                idempotency_key=f"cli-execution-resume-{execution_id}",
            ),
            json_output,
        )

    @executions.command("rollback")
    def executions_rollback(
        execution_id: str, json_output: bool = typer.Option(False, "--json")
    ) -> None:
        _emit(
            _request(
                settings,
                daemon_client_factory,
                "POST",
                f"/v1/workflow-runs/{execution_id}/rollback",
                idempotency_key=f"cli-execution-rollback-{execution_id}",
            ),
            json_output,
        )

    @approvals.command("list")
    def approvals_list(json_output: bool = typer.Option(False, "--json")) -> None:
        _emit(_request(settings, daemon_client_factory, "GET", "/v1/approvals"), json_output)

    @approvals.command("show")
    def approvals_show(approval_id: str, json_output: bool = typer.Option(False, "--json")) -> None:
        _emit(
            _request(settings, daemon_client_factory, "GET", f"/v1/approvals/{approval_id}"),
            json_output,
        )

    def decide_approval(approval_id: str, approved: bool, json_output: bool) -> None:
        _emit(
            _request(
                settings,
                daemon_client_factory,
                "POST",
                f"/v1/approvals/{approval_id}/decisions",
                {"status": "APPROVED" if approved else "REJECTED"},
                idempotency_key=f"cli-approval-{approval_id}-{approved}",
            ),
            json_output,
        )

    @approvals.command("approve")
    def approvals_approve(
        approval_id: str, json_output: bool = typer.Option(False, "--json")
    ) -> None:
        decide_approval(approval_id, True, json_output)

    @approvals.command("deny")
    def approvals_deny(approval_id: str, json_output: bool = typer.Option(False, "--json")) -> None:
        decide_approval(approval_id, False, json_output)

    @applications.command("list")
    def applications_list(json_output: bool = typer.Option(False, "--json")) -> None:
        _emit(_request(settings, daemon_client_factory, "GET", "/v1/apps"), json_output)

    @applications.command("inspect")
    def applications_inspect(
        application: str, json_output: bool = typer.Option(False, "--json")
    ) -> None:
        _emit(
            _request(
                settings, daemon_client_factory, "GET", f"/v1/apps/{application}/capabilities"
            ),
            json_output,
        )

    @applications.command("discover")
    def applications_discover(
        application: str, json_output: bool = typer.Option(False, "--json")
    ) -> None:
        _emit(
            _request(
                settings,
                daemon_client_factory,
                "GET",
                f"/v1/apps/{application}/capability-discovery",
            ),
            json_output,
        )

    @applications.command("capability-discovery")
    def applications_capability_discovery(
        application: str, json_output: bool = typer.Option(False, "--json")
    ) -> None:
        # Keep the established offline read-only inspection usable before the daemon
        # has initialized a token; live clients always use the authenticated route.
        if not settings.token_path.is_file():
            from mllminal.apps.service import ApplicationBridgeService

            report = asyncio.run(
                ApplicationBridgeService(
                    settings.database_path, settings.workspace_root
                ).capability_discovery(application)
            )
            if json_output:
                _emit(report.model_dump(mode="json"), True)
            else:
                typer.echo(report.model_dump_json())
            return
        applications_discover(application, json_output)

    @capabilities.command("list")
    def capabilities_list(json_output: bool = typer.Option(False, "--json")) -> None:
        _emit(_request(settings, daemon_client_factory, "GET", "/v1/providers"), json_output)

    @capabilities.command("inspect")
    def capabilities_inspect(
        capability: str, json_output: bool = typer.Option(False, "--json")
    ) -> None:
        _emit(
            _request(settings, daemon_client_factory, "GET", f"/v1/providers/resolve/{capability}"),
            json_output,
        )

    @capabilities.command("discover")
    def capabilities_discover(
        application: str, json_output: bool = typer.Option(False, "--json")
    ) -> None:
        applications_discover(application, json_output)

    @diagnostics.command("collect")
    def diagnostics_collect(json_output: bool = typer.Option(False, "--json")) -> None:
        _emit(_request(settings, daemon_client_factory, "GET", "/v1/status"), json_output)

    @diagnostics.command("inspect")
    def diagnostics_inspect(json_output: bool = typer.Option(False, "--json")) -> None:
        _emit(_request(settings, daemon_client_factory, "GET", "/v1/device/status"), json_output)

    @diagnostics.command("verify")
    def diagnostics_verify(archive: str, json_output: bool = typer.Option(False, "--json")) -> None:
        path = Path(archive).expanduser().resolve()
        try:
            with zipfile.ZipFile(path) as bundle:
                members = sorted(bundle.namelist())
        except (OSError, zipfile.BadZipFile) as error:
            typer.echo(f"Error: invalid diagnostic archive: {error}", err=True)
            raise typer.Exit(code=2) from None
        sensitive = ("token", ".db", "credential", "session")
        safe = not any(
            any(marker in member.casefold() for marker in sensitive) for member in members
        )
        result = {"archive": str(path), "valid": safe, "members": members}
        _emit(result, json_output)
        if not safe:
            raise typer.Exit(code=2)

    @service.command("status")
    def service_status(json_output: bool = typer.Option(False, "--json")) -> None:
        _emit(_request(settings, daemon_client_factory, "GET", "/v1/health"), json_output)

    @service.command("stop")
    def service_stop(json_output: bool = typer.Option(False, "--json")) -> None:
        _emit(
            _request(
                settings,
                daemon_client_factory,
                "POST",
                "/v1/daemon/shutdown",
                idempotency_key="cli-service-stop",
            ),
            json_output,
        )

    @service.command("start")
    def service_start(json_output: bool = typer.Option(False, "--json")) -> None:
        try:
            health = asyncio.run(daemon_client_factory(settings).health())
        except (OSError, RuntimeError, TimeoutError):
            _emit(_start_daemon(settings), json_output)
        else:
            _emit({"status": "already_running", "health": health}, json_output)

    @service.command("restart")
    def service_restart(json_output: bool = typer.Option(False, "--json")) -> None:
        with contextlib.suppress(typer.Exit):
            _request(
                settings,
                daemon_client_factory,
                "POST",
                "/v1/daemon/shutdown",
                idempotency_key="cli-service-restart-stop",
            )
        _emit(_start_daemon(settings), json_output)

    app.add_typer(workflows, name="workflows")
    app.add_typer(executions, name="executions")
    app.add_typer(approvals, name="approvals")
    app.add_typer(applications, name="applications")
    app.add_typer(capabilities, name="capabilities")
    app.add_typer(diagnostics, name="diagnostics")
    app.add_typer(service, name="service")
    app.add_typer(install, name="install")
