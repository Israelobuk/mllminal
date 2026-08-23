"""Interactive Mil session orchestration over the authenticated daemon client."""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
import sys
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.history import History
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.shortcuts import CompleteStyle
from prompt_toolkit.styles import Style

from mllminal.client.api import DaemonClient
from mllminal.client.interactive.commands import help_text, parse_command
from mllminal.client.interactive.completion import ContextResource, MilCompleter
from mllminal.client.interactive.history import LocalPromptHistory
from mllminal.client.interactive.renderer import ActivityItem, StartupSnapshot, TerminalRenderer
from mllminal.config import ProviderConfigStore, Settings

Output = Callable[[str], None]
Input = Callable[[str], str]
ClientFactory = Callable[[Settings], DaemonClient]


class InteractiveSession:
    """Own terminal presentation while leaving execution authority in the daemon."""

    def __init__(
        self,
        settings: Settings,
        client_factory: ClientFactory = DaemonClient,
        *,
        input_func: Input | None = None,
        output: Output | None = None,
        width: int | None = None,
        no_color: bool | None = None,
        use_prompt_toolkit: bool | None = None,
    ) -> None:
        self.settings = settings
        self.client = client_factory(settings)
        self.input_func = input_func or input
        self.output = output or print
        self.renderer = TerminalRenderer(width=width, no_color=no_color)
        self._use_prompt_toolkit = (
            sys.stdin.isatty() and sys.stdout.isatty()
            if use_prompt_toolkit is None
            else use_prompt_toolkit
        )
        self._prompt_session: PromptSession[str] | None = None
        self._snapshot: StartupSnapshot | None = None

    def run(self) -> None:
        self._show_startup()
        while True:
            try:
                line = self._read("\u203a ")
            except (EOFError, KeyboardInterrupt):
                self.output("\nSession ended.")
                return
            command = line.strip()
            if command in {"/exit", "/quit"}:
                self.output("Session ended.")
                return
            if command == "/begin":
                command = self._read_multiline()
            if not command:
                continue
            if command.startswith("/"):
                if self._handle_command(command):
                    return
                continue
            try:
                self._submit(command)
            except KeyboardInterrupt:
                self.output("^C\nCancelled current operation. The daemon remains running.")
            except (OSError, PermissionError, RuntimeError, TimeoutError, ValueError) as error:
                self.output(
                    self.renderer.error(
                        "Mil could not complete that request.",
                        str(error),
                        "Try /doctor for local runtime diagnostics.",
                    )
                )

    def _show_startup(self) -> None:
        try:
            snapshot, resources = asyncio.run(self._load_startup())
        except (AttributeError, OSError, PermissionError, RuntimeError, TimeoutError):
            snapshot, resources = self._fallback_startup()
        self._snapshot = snapshot
        self._configure_prompt(resources)
        self.output(self.renderer.startup(snapshot))

    async def _load_startup(self) -> tuple[StartupSnapshot, tuple[ContextResource, ...]]:
        request = getattr(self.client, "request", None)
        if not callable(request):
            return self._fallback_startup()
        paths = ("/v1/status", "/v1/tasks", "/v1/workflows", "/v1/workflow-runs", "/v1/apps")
        values = await asyncio.gather(
            *(request("GET", path) for path in paths), return_exceptions=True
        )
        status = values[0] if isinstance(values[0], dict) else {}
        tasks = values[1] if isinstance(values[1], list) else []
        workflows = values[2] if isinstance(values[2], list) else []
        workflow_runs = values[3] if isinstance(values[3], list) else []
        apps = values[4] if isinstance(values[4], list) else []
        daemon_online = str(status.get("daemon", "")).casefold() == "online"
        provider = str(status.get("provider", "local")).replace("_", " ").title()
        model = str(status.get("model", "local model"))
        resources = _workspace_resources(self.settings.workspace_root) + tuple(
            [
                ContextResource(
                    str(item.get("display_name") or item.get("application") or item.get("id")),
                    "application",
                    str(item.get("id") or item.get("application") or ""),
                )
                for item in apps
                if isinstance(item, dict) and item.get("id", item.get("application"))
            ]
            + [
                ContextResource(
                    str(item.get("name") or item.get("id")), "workflow", str(item.get("id"))
                )
                for item in workflows
                if isinstance(item, dict) and item.get("id")
            ]
        )
        quick_starts: list[str] = []
        if self.settings.workspace_root.is_dir():
            quick_starts.append("Summarize the files in this folder")
        if apps:
            quick_starts.append("What applications can Mil work with?")
        if workflows:
            quick_starts.append("Show my workflows")
        activity = _activity_items(tasks, workflow_runs)
        tip = (
            "Use @ to reference files, applications, and workflows."
            if resources
            else "Type / to browse commands."
        )
        first_run = not self._preferences_path().is_file()
        snapshot = StartupSnapshot(
            version=_package_version(),
            model=model,
            provider=provider,
            workspace=self.settings.workspace_root,
            runtime="Ready" if daemon_online else "Unavailable",
            recent_activity=tuple(activity[:3]),
            quick_starts=tuple(quick_starts[:4]),
            tip=tip,
            first_run=first_run,
        )
        self._mark_started()
        return snapshot, resources

    def _fallback_startup(self) -> tuple[StartupSnapshot, tuple[ContextResource, ...]]:
        snapshot = StartupSnapshot(
            version=_package_version(),
            model="local model",
            provider="unavailable",
            workspace=self.settings.workspace_root,
            runtime="Unavailable",
            quick_starts=("Summarize the files in this folder",)
            if self.settings.workspace_root.is_dir()
            else (),
            tip="Type /doctor for local runtime diagnostics.",
            first_run=not self._preferences_path().is_file(),
        )
        self._mark_started()
        return snapshot, ()

    def _configure_prompt(self, resources: Iterable[ContextResource]) -> None:
        if not self._use_prompt_toolkit:
            return
        history: History = LocalPromptHistory(self.settings.data_dir / "mil-history.jsonl")
        self._prompt_session = PromptSession(
            history=history,
            completer=MilCompleter(self.settings.workspace_root, resources),
            complete_while_typing=True,
            enable_history_search=True,
            placeholder=self.renderer.prompt_placeholder(),
            bottom_toolbar=self._footer,
            complete_style=CompleteStyle.COLUMN,
            reserve_space_for_menu=6,
            style=Style.from_dict(
                {
                    "": "fg:default",
                    "prompt": "bold",
                    "bottom-toolbar": "fg:#888888",
                    "completion-menu": "bg:#20242c",
                    "completion-menu.completion": "fg:#d9dce3",
                    "completion-menu.completion.current": "bg:#5b3fd6 fg:#ffffff",
                }
            ),
            output=DummyOutput() if not (sys.stdin.isatty() and sys.stdout.isatty()) else None,
        )

    def _read(self, prompt: str) -> str:
        if self._prompt_session is not None:
            message = (
                self.renderer.prompt_message()
                if prompt == self.renderer.prompt_prefix()
                else prompt
            )
            return self._prompt_session.prompt(
                message=message,
                placeholder=self.renderer.prompt_placeholder(),
                bottom_toolbar=self._footer,
            )
        return self.input_func(prompt)

    def _footer(self) -> str:
        if self._snapshot is None:
            return ""
        return self.renderer.footer(self._snapshot)

    def _read_multiline(self) -> str:
        lines: list[str] = []
        self.output("multiline mode; finish with /end")
        while True:
            try:
                part = self._read("... ")
            except KeyboardInterrupt:
                self.output("\nCancelled multiline input.")
                return ""
            if part.strip() == "/end":
                return "\n".join(lines).strip()
            lines.append(part)

    def _submit(self, content: str) -> None:
        from mllminal.client.mil import _submit

        asyncio.run(
            _submit(
                self.client,
                self.settings,
                content,
                output=self.output,
                input_func=self._read,
                stream_output=self._stream_output,
                approval_prompt=self.renderer.approval_prompt(),
                plan_renderer=self.renderer.plan,
                state_renderer=self.renderer.task_state,
                result_renderer=self.renderer.result,
            )
        )

    def _handle_command(self, line: str) -> bool:
        spec, argument = parse_command(line)
        if spec is None:
            self.output(
                self.renderer.error("Unknown command.", line, "Type /help to browse commands.")
            )
            return False
        try:
            if spec.name == "/help":
                self.output(help_text())
            elif spec.name == "/status":
                self.output(self._run(self._status_text()))
            elif spec.name == "/workspace":
                self.output(self._workspace_text(argument))
            elif spec.name == "/model":
                self.output(self._model_text())
            elif spec.name == "/apps":
                self.output(self._run(self._list_text("/v1/apps", "Applications")))
            elif spec.name == "/workflows":
                self.output(self._run(self._list_text("/v1/workflows", "Workflows")))
            elif spec.name == "/approvals":
                self.output(self._run(self._list_text("/v1/approvals", "Approvals")))
            elif spec.name == "/tasks":
                self.output(self._run(self._list_text("/v1/tasks", "Tasks")))
            elif spec.name == "/task":
                self.output(self._run(self._task_text(argument)))
            elif spec.name == "/history":
                self.output(self._run(self._history_text()))
            elif spec.name == "/context":
                self.output(self._run(self._context_text()))
            elif spec.name == "/compact":
                self.output(self._run(self._compact_text()))
            elif spec.name == "/clear":
                self._clear_session()
            elif spec.name == "/doctor":
                self.output(self._run(self._doctor_text()))
            elif spec.name == "/stop":
                self.output(
                    "Use Ctrl+C to cancel the current client operation. The daemon remains running."
                )
            elif spec.name == "/begin":
                self.output("Use /begin, enter your lines, then /end.")
        except (OSError, PermissionError, RuntimeError, TimeoutError, ValueError) as error:
            self.output(self.renderer.error("That command could not be completed.", str(error)))
        return False

    def _run(self, operation: Any) -> str:
        return str(asyncio.run(operation))

    async def _status_text(self) -> str:
        status = await self.client.request("GET", "/v1/status")
        tasks = await self.client.request("GET", "/v1/tasks")
        workflows = await self.client.request("GET", "/v1/workflows")
        apps = await self.client.request("GET", "/v1/apps")
        approvals = await self.client.request("GET", "/v1/approvals")
        status_dict = status if isinstance(status, dict) else {}
        task_count = len(tasks) if isinstance(tasks, list) else 0
        workflow_count = len(workflows) if isinstance(workflows, list) else 0
        app_count = len(apps) if isinstance(apps, list) else 0
        pending_count = _pending_count(approvals)
        return "\n".join(
            (
                "Runtime          "
                + ("Ready" if status_dict.get("daemon") == "Online" else "Unavailable"),
                f"Model            {status_dict.get('model', 'local model')}",
                f"Provider         {status_dict.get('provider', 'local')}",
                f"Workspace        {self.settings.workspace_root}",
                f"Apps             {app_count} discovered",
                f"Workflows        {workflow_count} available",
                f"Pending approvals {pending_count}",
                f"Tasks            {task_count}",
            )
        )

    async def _list_text(self, path: str, title: str) -> str:
        value = await self.client.request("GET", path)
        records = value if isinstance(value, list) else []
        if not records:
            return f"{title}\n\nNo {title.casefold()} available."
        lines = [title]
        for item in records:
            if not isinstance(item, dict):
                continue
            label = (
                item.get("display_name") or item.get("name") or item.get("title") or item.get("id")
            )
            state = item.get("state") or item.get("status") or "available"
            lines.append(f"  {self.renderer.status_line(str(label), str(state))}")
        return "\n".join(lines)

    async def _task_text(self, task_id: str) -> str:
        if not task_id:
            return "Usage: /task <id>"
        value = await self.client.request("GET", f"/v1/tasks/{task_id}")
        return _json_lines("Task", value)

    async def _history_text(self) -> str:
        session_id = await self._prepare_session()
        messages = await self.client.request("GET", f"/v1/sessions/{session_id}")
        records = messages.get("messages", []) if isinstance(messages, dict) else []
        if not records:
            return "No durable session messages."
        return "\n".join(
            f"{item.get('role', 'unknown')}: {item.get('content', '')}"
            for item in records
            if isinstance(item, dict)
        )

    async def _context_text(self) -> str:
        session_id = await self._prepare_session()
        value = await self.client.request("GET", f"/v1/sessions/{session_id}")
        records = value.get("messages", []) if isinstance(value, dict) else []
        count = len(records) if isinstance(records, list) else 0
        return (
            f"Context: {count} persisted messages; the daemon bounds the next request "
            "to its newest 20 messages."
        )

    async def _compact_text(self) -> str:
        session_id = await self._prepare_session()
        value = await self.client.request("GET", f"/v1/sessions/{session_id}")
        records = value.get("messages", []) if isinstance(value, dict) else []
        count = len(records) if isinstance(records, list) else 0
        return (
            f"Context bounded for the next request (newest 20 messages; currently {count}). "
            "Durable tasks and workflows were preserved."
        )

    async def _doctor_text(self) -> str:
        health = await self.client.health()
        return "\n".join(f"{key}: {value}" for key, value in health.items())

    async def _prepare_session(self) -> str:
        from mllminal.client.mil import _prepare_session

        return await _prepare_session(self.client, self.settings)

    def _workspace_text(self, argument: str) -> str:
        if not argument:
            return f"Current workspace:\n{self.settings.workspace_root}"
        candidate = Path(argument).expanduser().resolve()
        if not candidate.is_dir():
            raise ValueError("workspace must be an existing directory")
        self.settings.workspace_root = candidate
        self.client.session_id = None
        self._save_workspace(candidate)
        return f"Workspace changed to:\n{candidate}"

    def _model_text(self) -> str:
        config = ProviderConfigStore(self.settings).load()
        return "\n".join(
            (
                "Model",
                f"  {config.model}",
                f"  Provider: {config.provider}",
                "  Execution: Local",
                f"  Context limit: {config.max_context_tokens}",
            )
        )

    def _clear_session(self) -> None:
        from mllminal.client.mil import _session_path

        _session_path(self.settings).unlink(missing_ok=True)
        self.client.session_id = None
        self.output("Visible Mil conversation cleared. Durable tasks and workflows were preserved.")

    def _preferences_path(self) -> Path:
        return self.settings.data_dir / "mil-preferences.json"

    def _mark_started(self) -> None:
        try:
            self.settings.ensure_data_dir()
            current: dict[str, Any] = {}
            if self._preferences_path().is_file():
                value = json.loads(self._preferences_path().read_text(encoding="utf-8"))
                if isinstance(value, dict):
                    current = value
            current["startup_seen"] = True
            self._preferences_path().write_text(json.dumps(current) + "\n", encoding="utf-8")
        except (OSError, json.JSONDecodeError):
            return

    def _save_workspace(self, workspace: Path) -> None:
        try:
            self.settings.ensure_data_dir()
            self._preferences_path().write_text(
                json.dumps({"startup_seen": True, "workspace": str(workspace)}) + "\n",
                encoding="utf-8",
            )
        except OSError:
            return


def _activity_items(tasks: list[object], workflow_runs: list[object]) -> list[ActivityItem]:
    records = [item for item in (*tasks, *workflow_runs) if isinstance(item, dict)]
    records.sort(
        key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True
    )
    return [
        ActivityItem(
            str(item.get("title") or item.get("name") or item.get("id") or "Task"),
            str(item.get("state") or item.get("status") or "pending"),
            _age(item.get("updated_at") or item.get("created_at")),
        )
        for item in records[:3]
    ]


def _workspace_resources(workspace: Path, *, limit: int = 32) -> tuple[ContextResource, ...]:
    try:
        if not workspace.is_dir():
            return ()
        entries = sorted(workspace.iterdir(), key=lambda item: item.name.casefold())
    except OSError:
        return ()
    resources: list[ContextResource] = []
    for entry in entries:
        if entry.name.startswith(".") or entry.name in {"__pycache__", ".venv"}:
            continue
        try:
            is_folder = entry.is_dir()
        except OSError:
            continue
        kind = "folder" if is_folder else "file"
        value = entry.relative_to(workspace).as_posix()
        label = entry.name
        if is_folder:
            value += "/"
            label += "/"
        resources.append(ContextResource(label, kind, value))
        if len(resources) >= limit:
            break
    return tuple(resources)


def _age(value: object) -> str:
    if not isinstance(value, str) or not value:
        return ""
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    seconds = max(0, int((datetime.now(UTC) - timestamp).total_seconds()))
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return "yesterday" if seconds < 172800 else f"{seconds // 86400}d ago"


def _json_lines(title: str, value: object) -> str:
    return f"{title}\n{json.dumps(value, indent=2, default=str)}"


def _package_version() -> str:
    try:
        return importlib.metadata.version("mllminal")
    except importlib.metadata.PackageNotFoundError:
        return "0.1.0"


def _pending_count(value: object) -> int:
    if not isinstance(value, list):
        return 0
    return sum(
        1
        for item in value
        if isinstance(item, dict) and str(item.get("status", "")).casefold() == "pending"
    )
