"""Small, responsive, terminal-native rendering primitives for Mil."""

from __future__ import annotations

import os
import shutil
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
        if snapshot.first_run:
            return self._onboarding(snapshot)
        if self.terminal_width >= 90:
            return self._wide(snapshot)
        if self.terminal_width >= 60:
            return self._medium(snapshot)
        return self._narrow(snapshot)

    def status_line(self, label: str, state: str) -> str:
        symbol = (
            "●"
            if label.casefold() == "runtime" and state.casefold() == "ready"
            else self._symbol(state)
        )
        return f"{label}: {symbol} {state}"

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

    def _wide(self, snapshot: StartupSnapshot) -> str:
        recent = [f"  {self.activity(item)}" for item in snapshot.recent_activity[:3]]
        if not recent:
            recent = ["  No recent activity"]
        left = [
            f"Workspace: {snapshot.workspace}",
            self.status_line("Runtime", snapshot.runtime),
            f"Privacy: {snapshot.privacy}",
        ]
        right = [
            "Quick start",
            *(f'  "{item}"' for item in snapshot.quick_starts[:4]),
            "",
            "Recent activity",
            *recent,
        ]
        width = min(self.terminal_width - 4, max(62, self.terminal_width - 6))
        split = max(28, width // 2)
        rows = [
            self._fit(f"MLLminal {snapshot.version}", width),
            self._fit(f"Mil · {snapshot.model} · {snapshot.provider}", width),
            "",
            self._fit(
                "  ".join((left[0], " " * max(1, split - len(left[0]) - 2), right[0])), width
            ),
        ]
        for index in range(max(len(left), len(right))):
            left_value = left[index] if index < len(left) else ""
            right_value = right[index] if index < len(right) else ""
            rows.append(self._fit(f"{left_value:<{split}}  {right_value}", width))
        rows.extend(("", self._fit(f"Tip: {snapshot.tip}", width), "Type /help for commands"))
        return self._box(rows, width)

    def _medium(self, snapshot: StartupSnapshot) -> str:
        recent = [f"  {self.activity(item)}" for item in snapshot.recent_activity[:3]]
        if not recent:
            recent = ["  No recent activity"]
        rows = [
            f"MLLminal {snapshot.version}",
            f"Mil · {snapshot.model} · {snapshot.provider}",
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
            f"Mil · {snapshot.model}",
            self._fit(f"Workspace: {snapshot.workspace}"),
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
        top = "╭" + "─" * inner + "╮"
        bottom = "╰" + "─" * inner + "╯"
        body = [f"│ {row:<{inner - 1}}│" for row in rows]
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
            return "✓"
        if normalized in {"running", "active", "executing", "verifying"}:
            return "●"
        if normalized in {"pending", "waiting", "needs input"}:
            return "○"
        if normalized in {"failed", "error", "unavailable", "warning"}:
            return "!"
        return "·"
