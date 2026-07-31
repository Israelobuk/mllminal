"""Connected keyboard-first Textual client for the local MLLminal daemon."""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Footer, Header, Input, RichLog, Static, TabbedContent, TabPane

from mllminal.client.api import DaemonClient, DesktopSnapshot, DesktopState
from mllminal.config import Settings
from mllminal.service_lifecycle import ensure_daemon


class MLLminalDesktopApp(App[None]):
    TITLE = "MLLminal"
    SUB_TITLE = "Connected local workflow intelligence"
    CSS = """
    Screen { background: $surface; }
    #dashboard { width: 100%; height: 1fr; padding: 1 2; }
    #connection { height: auto; padding: 1 2; border: round $accent; background: $panel; }
    #state { text-style: bold; color: $success; }
    #stale { color: $warning; }
    #pages { height: 1fr; margin: 1 0 0 0; }
    TabPane { padding: 1 0; }
    #columns { height: 1fr; }
    .panel {
        width: 1fr; height: 1fr; margin: 1 1 0 0; padding: 1 2;
        border: round $accent; background: $panel;
    }
    .page-panel { height: 1fr; padding: 1 2; border: round $secondary; background: $panel; }
    .page-title { text-style: bold; color: $accent; }
    #terminal { height: 10; border: round $secondary; padding: 1; }
    Input { margin: 1 0; }
    Button { margin: 0 1 0 0; }
    #emergency { background: $error; }
    """
    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        ("q", "quit", "Quit"),
        ("p", "pause", "Pause observation"),
        ("e", "emergency", "Emergency stop"),
        ("r", "refresh", "Refresh"),
        ("1", "show_mil", "Mil"),
        ("2", "show_status", "Status"),
        ("3", "show_workflows", "Workflows"),
        ("4", "show_executions", "Executions"),
        ("5", "show_approvals", "Approvals"),
        ("6", "show_applications", "Applications"),
        ("7", "show_capabilities", "Capabilities"),
        ("8", "show_policies", "Policies"),
        ("9", "show_diagnostics", "Diagnostics"),
        ("0", "show_settings", "Settings"),
    ]

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self.settings = settings or Settings()
        self.client = DaemonClient(self.settings)
        self.snapshot = DesktopSnapshot(DesktopState.DAEMON_STARTING)
        self.last_event_sequence = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll(id="dashboard"):
            with Vertical(id="connection"):
                yield Static("Daemon: starting", id="state")
                yield Static("Connecting to the local authenticated daemon", id="connection-detail")
                yield Static("State has not been refreshed yet", id="stale")
            with TabbedContent(
                "Mil chat",
                "System status",
                "Workflows",
                "Executions",
                "Approvals",
                "Applications",
                "Capabilities",
                "Active policies",
                "Diagnostics",
                "Settings",
                initial="mil",
                id="pages",
            ):
                with TabPane("Mil chat", id="mil"), Horizontal(id="columns"):
                    with Vertical(classes="panel"):
                        yield Static("Daemon-owned state", classes="panel-title")
                        yield Static(
                            "Tasks: ?\nWorkflows: ?\nApprovals: ?\nVerification: ?",
                            id="shared-state",
                        )
                        yield Static(
                            "Observation: ?\nPrivacy: ?\nPermissions: ?\nPolicy: ?",
                            id="privacy-state",
                        )
                        with Horizontal():
                            yield Button("Pause observation", id="pause")
                            yield Button("Emergency stop", id="emergency", variant="error")
                    with Vertical(classes="panel"):
                        yield Static("Mil / workflow controls", classes="panel-title")
                        yield Input(placeholder="Message Mil?", id="chat-input")
                        with Horizontal():
                            yield Button("Send to Mil", id="send")
                            yield Button("Start demonstration", id="demo")
                        yield Input(placeholder="Demonstration label", id="demo-label")
                        yield Static("Latest visual verification: ?", id="verification")
                        yield Static("Suggestions: ?\nPreferences: ?", id="suggestions")
                with TabPane("System status", id="status"):
                    yield Static("System status", classes="page-title")
                    yield Static("Waiting for daemon state", id="page-status", classes="page-panel")
                with TabPane("Workflows", id="workflows"):
                    yield Static("Workflows", classes="page-title")
                    yield Static(
                        "Waiting for workflow definitions",
                        id="page-workflows",
                        classes="page-panel",
                    )
                with TabPane("Executions", id="executions"):
                    yield Static("Executions", classes="page-title")
                    yield Static(
                        "Waiting for durable execution state",
                        id="page-executions",
                        classes="page-panel",
                    )
                with TabPane("Approvals", id="approvals"):
                    yield Static("Approvals", classes="page-title")
                    yield Static(
                        "Waiting for approval state", id="page-approvals", classes="page-panel"
                    )
                with TabPane("Applications", id="applications"):
                    yield Static("Applications", classes="page-title")
                    yield Static(
                        "Waiting for application discovery",
                        id="page-applications",
                        classes="page-panel",
                    )
                with TabPane("Capabilities", id="capabilities"):
                    yield Static("Capabilities", classes="page-title")
                    yield Static(
                        "Capabilities remain daemon-resolved and permission-bounded.",
                        id="page-capabilities",
                        classes="page-panel",
                    )
                with TabPane("Active policies", id="policies"):
                    yield Static("Active policies", classes="page-title")
                    yield Static(
                        "Waiting for policy runtime status",
                        id="page-policies",
                        classes="page-panel",
                    )
                with TabPane("Diagnostics", id="diagnostics"):
                    yield Static("Diagnostics", classes="page-title")
                    yield Static(
                        "Waiting for diagnostics", id="page-diagnostics", classes="page-panel"
                    )
                with TabPane("Settings", id="settings"):
                    yield Static("Settings", classes="page-title")
                    yield Static(
                        "Settings are local configuration; execution authority remains "
                        "in the daemon.",
                        id="page-settings",
                        classes="page-panel",
                    )
            yield RichLog(id="terminal", highlight=False, markup=False)
            yield Static(
                "Keyboard: 1-0 pages · r refresh · p pause · e emergency stop · q quit",
                id="terminal-label",
            )
        yield Footer()

    async def on_mount(self) -> None:
        self.set_interval(3.0, self._schedule_refresh)
        self.run_worker(self._event_loop(), group="events")
        self._schedule_refresh()

    def _schedule_refresh(self) -> None:
        self.run_worker(self._refresh(), exclusive=True, group="refresh")

    async def _refresh(self) -> None:
        self.snapshot = await self.client.snapshot()
        self._render_snapshot()

    def _render_snapshot(self) -> None:
        snapshot = self.snapshot
        self.query_one("#state", Static).update(f"Daemon: {snapshot.state.value}")
        detail = snapshot.error or "Authenticated local daemon state is shared with CLI clients."
        self.query_one("#connection-detail", Static).update(detail)
        self.query_one("#stale", Static).update(
            "Live event stream connected"
            if snapshot.state is not DesktopState.DAEMON_UNAVAILABLE
            else "Stale: reconnecting to daemon"
        )
        approvals = sum(
            1 for task in snapshot.tasks if str(task.get("state")) == "WAITING_FOR_APPROVAL"
        )
        failures = sum(1 for task in snapshot.tasks if str(task.get("state")) == "FAILED")
        self.query_one("#shared-state", Static).update(
            f"Tasks: {len(snapshot.tasks)}\nWorkflows: {len(snapshot.workflows)}\n"
            f"Applications: {len(snapshot.applications)}\nApprovals: {approvals}\n"
            f"Verification failures: {failures}"
        )
        policy_state = (
            "active" if snapshot.active_policy.get("active") else "deterministic fallback"
        )
        verification_state = (
            "active" if snapshot.verification_policy.get("active") else "deterministic fallback"
        )
        self.query_one("#privacy-state", Static).update(
            f"Observation: {snapshot.device.get('state', '?')}\n"
            f"Privacy: {'paused' if snapshot.privacy.get('paused') else 'active'}\n"
            f"Permissions: {len(snapshot.permissions)}\n"
            f"Policy: {policy_state}\nVerification policy: {verification_state}"
        )
        self.query_one("#suggestions", Static).update(
            f"Suggestions: {len(snapshot.suggestions)}\n"
            f"Preferences: {len(snapshot.suggestion_preferences)}\n"
            "Suggestions remain review-only."
        )
        visual = snapshot.visual or {}
        self.query_one("#verification", Static).update(
            "Latest visual verification: "
            + (
                f"{visual.get('application', 'unknown')} / {visual.get('provider', 'unknown')}"
                if visual
                else "?"
            )
        )
        self.query_one("#page-status", Static).update(
            f"Daemon: {snapshot.state.value}\nProvider: {snapshot.status.get('provider', '?')}\n"
            f"Tasks: {len(snapshot.tasks)}\nPermissions: {len(snapshot.permissions)}"
        )
        self.query_one("#page-workflows", Static).update(
            f"Definitions: {len(snapshot.workflows)}\nRuns: {len(snapshot.workflow_runs)}\n"
            "Use mllminal workflows for proposals and validation."
        )
        self.query_one("#page-executions", Static).update(
            "\n".join(
                f"{item.get('id', '?')}: {item.get('state', '?')}"
                for item in snapshot.workflow_runs
            )
            or "No durable executions."
        )
        self.query_one("#page-approvals", Static).update(
            f"Pending task approvals: {approvals}\nApproval decisions remain daemon-authorized."
        )
        self.query_one("#page-applications", Static).update(
            "\n".join(
                str(item.get("name", item.get("application", "unknown")))
                for item in snapshot.applications
            )
            or "No discovered application surfaces."
        )
        self.query_one("#page-policies", Static).update(
            f"Active policy: {snapshot.active_policy.get('active', False)}\n"
            f"Verification policy: {snapshot.verification_policy.get('active', False)}\n"
            f"Runtime projection: {snapshot.active_policies.get('live_runtime_domains', [])}"
        )
        self.query_one("#page-diagnostics", Static).update(
            f"Daemon state: {snapshot.state.value}\nLast error: {snapshot.error or 'none'}\n"
            "Diagnostics are bounded projections; raw database rows are not exposed."
        )
        if snapshot.state is DesktopState.EMERGENCY_STOP_ACTIVE:
            self.query_one("#emergency", Button).label = "Emergency stop active"

    async def _event_loop(self) -> None:
        while True:
            try:
                async for event in self.client.stream_events(self.last_event_sequence):
                    if isinstance(event, dict):
                        self.last_event_sequence = max(
                            self.last_event_sequence, int(event.get("sequence", 0))
                        )
                        event_type = event.get("event_type", event.get("type", "update"))
                        payload = event.get("payload", {})
                        self.query_one("#terminal", RichLog).write(f"event {event_type}: {payload}")
                        self._schedule_refresh()
            except (PermissionError, OSError, TimeoutError, RuntimeError) as error:
                self.query_one("#terminal", RichLog).write(
                    f"event stream unavailable; retrying: {error}"
                )
                self.query_one("#stale", Static).update("Stale: event stream reconnecting")
                await asyncio.sleep(3)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "pause":
            self.run_worker(self._perform("pause"), group="actions")
        elif event.button.id == "emergency":
            self.run_worker(self._perform("emergency"), group="actions")
        elif event.button.id == "send":
            self.run_worker(self._send_chat(), group="actions")
        elif event.button.id == "demo":
            self.run_worker(self._start_demo(), group="actions")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "chat-input" and event.value.strip():
            await self._send_chat()

    async def _perform(self, action: str) -> None:
        try:
            if action == "pause":
                await self.client.pause_observation()
            else:
                await self.client.emergency_stop()
            await self._refresh()
        except (PermissionError, OSError, RuntimeError) as error:
            self.query_one("#terminal", RichLog).write(f"{action} failed: {error}")

    async def _send_chat(self) -> None:
        input_widget = self.query_one("#chat-input", Input)
        content = input_widget.value.strip()
        if not content:
            return
        terminal = self.query_one("#terminal", RichLog)
        try:
            pending: dict[str, Any] | None = None
            async for item in self.client.stream_chat(content):
                item_type = item.get("type")
                if item_type == "event":
                    event = item.get("event", {})
                    if event.get("event_type") == "response.delta":
                        payload = event.get("payload", {})
                        delta = payload.get("text") if isinstance(payload, dict) else None
                        if isinstance(delta, str):
                            terminal.write(delta)
                elif item_type == "pending" and isinstance(item.get("pending"), dict):
                    pending = item["pending"]
                elif item_type == "error":
                    error = item.get("error", {})
                    message = error.get("message") if isinstance(error, dict) else None
                    raise RuntimeError(str(message or "Mil provider failed"))
            if pending is None:
                raise RuntimeError("daemon ended the Mil stream without a pending task")
            terminal.write(f"Mil task proposed: {pending}")
            input_widget.value = ""
            await self._refresh()
        except (PermissionError, OSError, RuntimeError) as error:
            terminal.write(f"chat failed: {error}")

    async def _start_demo(self) -> None:
        label_widget = self.query_one("#demo-label", Input)
        label = label_widget.value.strip() or "Terminal demonstration"
        try:
            response = await self.client.start_demonstration(label)
            self.query_one("#terminal", RichLog).write(f"demonstration: {response}")
            await self._refresh()
        except (PermissionError, OSError, RuntimeError) as error:
            self.query_one("#terminal", RichLog).write(f"demonstration failed: {error}")

    def _show(self, page: str) -> None:
        self.query_one("#pages", TabbedContent).active = page

    def action_pause(self) -> None:
        self.run_worker(self._perform("pause"), group="actions")

    def action_emergency(self) -> None:
        self.run_worker(self._perform("emergency"), group="actions")

    def action_refresh(self) -> None:
        self._schedule_refresh()

    def action_show_mil(self) -> None:
        self._show("mil")

    def action_show_status(self) -> None:
        self._show("status")

    def action_show_workflows(self) -> None:
        self._show("workflows")

    def action_show_executions(self) -> None:
        self._show("executions")

    def action_show_approvals(self) -> None:
        self._show("approvals")

    def action_show_applications(self) -> None:
        self._show("applications")

    def action_show_capabilities(self) -> None:
        self._show("capabilities")

    def action_show_policies(self) -> None:
        self._show("policies")

    def action_show_diagnostics(self) -> None:
        self._show("diagnostics")

    def action_show_settings(self) -> None:
        self._show("settings")


def main() -> None:
    settings = Settings()
    try:
        asyncio.run(ensure_daemon(settings))
    except (OSError, RuntimeError, TimeoutError):
        raise SystemExit(3) from None
    MLLminalDesktopApp(settings).run()


if __name__ == "__main__":
    main()
