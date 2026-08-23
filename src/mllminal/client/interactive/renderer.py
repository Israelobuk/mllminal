"""Small, responsive, terminal-native rendering primitives for Mil."""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ActivityItem:
    label: str
    state: str = "completed"
    age: str = ""


@dataclass(frozen=True, slots=True)
class StartupSnapshot:
    version: str
    model: str
    provider: str
    workspace: Path
    runtime: str
    recent_activity: tuple[ActivityItem, ...] = ()
    quick_starts: tuple[str, ...] = ()
    tip: str = "Type / to browse commands."
    privacy: str = "Local-first"
    first_run: bool = False
    context: str | None = None


@dataclass(slots=True)
class TerminalRenderer:
    """Render bounded output that remains readable without ANSI support."""

    width: int | None = None
    no_color: bool | None = None
    _ansi: bool = field(init=False, repr=False)

    def __post_init__(self) -> None:
        width = self.width or shutil.get_terminal_size((80, 24)).columns
        self.width = max(32, width)
        is_tty = os.isatty(1)
        self._ansi = not bool(self.no_color or os.environ.get("NO_COLOR") is not None) and is_tty

    def startup(self, snapshot: StartupSnapshot) -> str:
        return self._welcome(snapshot)

    def _welcome(self, snapshot: StartupSnapshot) -> str:
        greeting = "Welcome to MLLminal" if snapshot.first_run else "Welcome back"
        workspace = self._workspace_display(snapshot.workspace)
        recent = [self.activity(item) for item in snapshot.recent_activity[:3]]
        if not recent:
            recent = ["No recent activity"]
        suggestions = ["Help me understand this project", *snapshot.quick_starts[:2]]
        rows = [
            "MLLminal",
            f"Mil - {snapshot.model} - {snapshot.provider}",
            "Local workflow intelligence for your computer.",
            "",
            greeting,
            "What would you like to work on?",
            "",
            "Session",
            f"  Workspace: {workspace}",
            f"  {self.status_line('Runtime', snapshot.runtime)}",
            f"  Model: {snapshot.model}",
            f"  Privacy: {snapshot.privacy}",
            "",
            "Getting started",
            "Try asking",
            *(f"  {item}" for item in suggestions),
            "",
            "Recent activity",
            *(f"  {item}" for item in recent),
            "",
            "Commands",
            "  /help  browse commands   /status  check health   /exit  leave",
            "",
            f"Tip: {snapshot.tip}",
        ]
        return "\n".join(self._fit(row) for row in rows)

    def status_line(self, label: str, state: str) -> str:
        symbol = (
            "*"
            if label.casefold() == "runtime" and state.casefold() == "ready"
            else self._symbol(state)
        )
        return f"{label}: {symbol} {state}"

    def footer(self, snapshot: StartupSnapshot) -> str:
        workspace = snapshot.workspace.name or self._workspace_display(snapshot.workspace)
        return self._fit(
            f"{snapshot.model} - {snapshot.provider} | {workspace} | "
            f"{self._runtime_badge(snapshot.runtime)} | / commands | @ context"
        )

    @staticmethod
    def prompt_placeholder() -> str:
        return "Ask Mil to work with your files, apps, or workflows..."

    @staticmethod
    def prompt_prefix() -> str:
        return "> "

    def user_message(self, content: str) -> str:
        rows = ["", "You", f"> {content}"]
        return "\n".join(self._fit(row) for row in rows)

    @staticmethod
    def mil_prefix() -> str:
        return "\nMil\n"

    def prompt_message(self) -> str:
        return f"\n{self.prompt_prefix()}"

    def plan(self, steps: Iterable[str]) -> str:
        rows = ["Plan ready", "Review the proposed bounded actions:"]
        rows.extend(f"{index}. {step}" for index, step in enumerate(steps, start=1))
        rows.extend(["", "Approval required - no action has run."])
        return self._box(rows, self.terminal_width)

    def approval_prompt(self) -> str:
        return f"\nApproval required\n[A] Approve plan   [L] Leave pending\n{self.prompt_prefix()}"

    def task_state(self, state: str) -> str:
        return self._box(
            [f"Task status: {state}", "Daemon owns execution and verification."],
            self.terminal_width,
        )

    def result(self, state: str) -> str:
        if state == "COMPLETED":
            rows = ["Verified completion", "The daemon confirmed the final state."]
        else:
            rows = [f"Execution ended: {state}", "Review the daemon task for details."]
        return self._box(rows, self.terminal_width)

    def error(self, title: str, detail: str | None = None, hint: str | None = None) -> str:
        lines = [f"! {title}"]
        if detail:
            lines.append(f"  {detail}")
        if hint:
            lines.append(f"  {hint}")
        return "\n".join(self._fit(line) for line in lines)

    def activity(self, item: ActivityItem) -> str:
        suffix = f"  {item.age}" if item.age else ""
        return self._fit(f"{self._symbol(item.state)} {item.label}{suffix}")

    def _card(self, snapshot: StartupSnapshot, *, wide: bool) -> str:
        greeting = "Welcome to MLLminal" if snapshot.first_run else "Welcome back"
        identity = f"Mil - {snapshot.model} - {snapshot.provider}"
        provider = "Local workflow intelligence"
        workspace = self._workspace_display(snapshot.workspace)
        recent = [self.activity(item) for item in snapshot.recent_activity[:3]]
        if not recent:
            recent = ["No recent activity"]
        getting_started = [
            "Getting started",
            "Type / to browse commands",
            "Use @ to add context",
            "Ask Mil to work with your files",
        ]
        left = [
            greeting,
            identity,
            provider,
            "",
            "Workspace:",
            workspace,
            "",
            "Runtime",
            self._runtime_badge(snapshot.runtime),
            f"Privacy: {snapshot.privacy}",
        ]
        right = [*getting_started]
        if snapshot.quick_starts:
            right.extend(["", "Try", *snapshot.quick_starts[:2]])
        right.extend(["", "Recent activity", *recent])
        if wide:
            rows = [
                f"MLLminal v{snapshot.version}",
                "",
                *self._column_rows(left, right),
                "",
                f"Tip: {snapshot.tip}",
            ]
        else:
            rows = [
                f"MLLminal v{snapshot.version}",
                *left,
                "",
                *right,
                "",
                f"Tip: {snapshot.tip}",
            ]
        return self._box(rows, self.terminal_width)

    def _column_rows(self, left: list[str], right: list[str]) -> list[str]:
        content_width = max(1, self.terminal_width - 3)
        gap = 3
        column_width = max(1, (content_width - gap) // 2)
        rows: list[str] = []
        for index in range(max(len(left), len(right))):
            left_value = self._fit(left[index] if index < len(left) else "", column_width)
            right_value = self._fit(right[index] if index < len(right) else "", column_width)
            rows.append(f"{left_value:<{column_width}}{' ' * gap}{right_value}")
        return rows

    @staticmethod
    def _workspace_display(workspace: Path) -> str:
        try:
            relative = workspace.resolve().relative_to(Path.home().resolve())
        except (OSError, ValueError):
            return str(workspace)
        return "~" if not relative.parts else "~" + str(Path(*relative.parts))

    @staticmethod
    def _runtime_badge(state: str) -> str:
        normalized = state.casefold()
        if normalized in {"ready", "online", "ok"}:
            return "* Ready"
        if normalized in {"starting", "booting"}:
            return "o Starting"
        if normalized in {"degraded", "warning"}:
            return "! Degraded"
        if normalized in {"offline", "unavailable", "stopped"}:
            return "x Offline"
        return f"- {state}"

    def _medium(self, snapshot: StartupSnapshot) -> str:
        recent = [f"  {self.activity(item)}" for item in snapshot.recent_activity[:3]]
        if not recent:
            recent = ["  No recent activity"]
        rows = [
            f"MLLminal {snapshot.version}",
            f"Mil - {snapshot.model} - {snapshot.provider}",
            f"Workspace: {snapshot.workspace}",
            self.status_line("Runtime", snapshot.runtime),
            f"Privacy: {snapshot.privacy}",
            "",
            "Quick start",
            *(f"  {item}" for item in snapshot.quick_starts[:3]),
            "",
            "Recent activity",
            *recent,
            "",
            f"Tip: {snapshot.tip}",
            "Type /help for commands",
        ]
        return "\n".join(self._fit(row) for row in rows)

    def _narrow(self, snapshot: StartupSnapshot) -> str:
        rows = [
            "MLLminal",
            f"Mil - {snapshot.model} - {snapshot.provider}",
            self._fit(f"Workspace: {self._workspace_display(snapshot.workspace)}"),
            self._fit(self.status_line("Runtime", snapshot.runtime)),
            f"Tip: {snapshot.tip}",
            "",
            "Type /help for commands",
        ]
        return "\n".join(self._fit(row) for row in rows)

    def _onboarding(self, snapshot: StartupSnapshot) -> str:
        rows = [
            f"Welcome to MLLminal {snapshot.version}",
            "",
            "Mil works with local files, applications, and workflows.",
            f"Workspace: {snapshot.workspace}",
            "",
            "Try:",
            '  "summarize the files in this folder"',
            "",
            "Type /help at any time.",
        ]
        return "\n".join(self._fit(row) for row in rows)

    @property
    def terminal_width(self) -> int:
        return self.width or 80

    def _box(self, rows: list[str], width: int) -> str:
        inner = max(1, width - 2)
        top = "+" + "-" * inner + "+"
        bottom = "+" + "-" * inner + "+"
        body = [f"| {self._fit(row, inner - 1):<{inner - 1}}|" for row in rows]
        return "\n".join((top, *body, bottom))

    def _fit(self, value: str, width: int | None = None) -> str:
        limit = width or self.width or 80
        if len(value) <= limit:
            return value
        if limit < 4:
            return value[:limit]
        return value[: limit - 3] + "..."

    @staticmethod
    def _symbol(state: str) -> str:
        normalized = state.casefold()
        if normalized in {"ready", "completed", "complete", "success", "ok"}:
            return "+"
        if normalized in {"running", "active", "executing", "verifying"}:
            return "*"
        if normalized in {"pending", "waiting", "needs input"}:
            return "o"
        if normalized in {"failed", "error", "unavailable", "warning"}:
            return "!"
        return "-"
