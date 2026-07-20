"""Connected thin desktop surface for the local MLLminal daemon."""

from __future__ import annotations

import asyncio
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Footer, Header, Input, RichLog, Static

from mllminal.client.api import DaemonClient, DesktopSnapshot, DesktopState


class MLLminalDesktopApp(App[None]):
    TITLE = "MLLminal"
    SUB_TITLE = "Connected local workflow intelligence"
    CSS = """
    Screen {
        background: $surface;
    }
    #dashboard {
        width: 100%;
        height: 1fr;
        padding: 1 2;
    }
    #connection {
        height: auto;
        padding: 1 2;
        border: round $accent;
        background: $panel;
    }
    #state {
        text-style: bold;
        color: $success;
    }
    #columns {
        height: 1fr;
    }
    .panel {
        width: 1fr;
        height: 1fr;
        margin: 1 1 0 0;
        padding: 1 2;
        border: round $accent;
        background: $panel;
    }
    #terminal {
        height: 10;
        border: round $secondary;
        padding: 1;
    }
    Input {
        margin: 1 0;
    }
    Button {
        margin: 0 1 0 0;
    }
    #emergency {
        background: $error;
    }
    """
    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        ("q", "quit", "Quit"),
        ("p", "pause", "Pause observation"),
        ("e", "emergency", "Emergency stop"),
        ("r", "refresh", "Refresh"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.client = DaemonClient()
        self.snapshot = DesktopSnapshot(DesktopState.DAEMON_STARTING)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll(id="dashboard"):
            with Vertical(id="connection"):
                yield Static("Daemon: starting", id="state")
                yield Static(
                    "Connecting to the local authenticated daemon?", id="connection-detail"
                )
            with Horizontal(id="columns"):
                with Vertical(classes="panel"):
                    yield Static("Shared state", classes="panel-title")
                    yield Static(
                        "Tasks: ?\nWorkflows: ?\nApprovals: ?\nVerification: ?", id="shared-state"
                    )
                    yield Static("Observation: ?\nPrivacy: ?\nPermissions: ?", id="privacy-state")
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
            yield RichLog(id="terminal", highlight=False, markup=False)
            yield Static(
                "Embedded terminal view ? mllminal tasks ? mllminal events ? "
                "daemon owns execution and state",
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
        approvals = sum(
            1 for task in snapshot.tasks if str(task.get("state")) == "WAITING_FOR_APPROVAL"
        )
        verification = sum(1 for task in snapshot.tasks if str(task.get("state")) == "FAILED")
        self.query_one("#shared-state", Static).update(
            f"Tasks: {len(snapshot.tasks)}\n"
            f"Workflows: {len(snapshot.workflows)}\n"
            f"Approvals: {approvals}\n"
            f"Verification failures: {verification}"
        )
        self.query_one("#privacy-state", Static).update(
            f"Observation: {snapshot.device.get('state', '?')}\n"
            f"Privacy: {'paused' if snapshot.privacy.get('paused') else 'active'}\n"
            f"Permissions: {len(snapshot.permissions)}"
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
        if snapshot.state is DesktopState.EMERGENCY_STOP_ACTIVE:
            self.query_one("#emergency", Button).label = "Emergency stop active"

    async def _event_loop(self) -> None:
        sequence = 0
        while True:
            try:
                async for event in self.client.stream_events(sequence):
                    if isinstance(event, dict):
                        sequence = max(sequence, int(event.get("sequence", sequence)))
                        self.query_one("#terminal", RichLog).write(
                            f"event {event.get('event_type', event.get('type', 'update'))}: {event}"
                        )
                        self._schedule_refresh()
            except (PermissionError, OSError, TimeoutError, RuntimeError) as error:
                self.query_one("#terminal", RichLog).write(f"event stream unavailable: {error}")
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
        try:
            response = await self.client.chat(content)
            self.query_one("#terminal", RichLog).write(f"Mil task: {response}")
            input_widget.value = ""
            await self._refresh()
        except (PermissionError, OSError, RuntimeError) as error:
            self.query_one("#terminal", RichLog).write(f"chat failed: {error}")

    async def _start_demo(self) -> None:
        label_widget = self.query_one("#demo-label", Input)
        label = label_widget.value.strip() or "Desktop demonstration"
        try:
            response = await self.client.start_demonstration(label)
            self.query_one("#terminal", RichLog).write(f"demonstration: {response}")
            await self._refresh()
        except (PermissionError, OSError, RuntimeError) as error:
            self.query_one("#terminal", RichLog).write(f"demonstration failed: {error}")

    def action_pause(self) -> None:
        self.run_worker(self._perform("pause"), group="actions")

    def action_emergency(self) -> None:
        self.run_worker(self._perform("emergency"), group="actions")

    def action_refresh(self) -> None:
        self._schedule_refresh()


def main() -> None:
    MLLminalDesktopApp().run()


if __name__ == "__main__":
    main()
