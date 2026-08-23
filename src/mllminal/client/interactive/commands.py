"""Discoverable slash-command metadata used by the interactive Mil shell."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CommandSpec:
    name: str
    description: str
    group: str
    takes_argument: bool = False


_COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec("/status", "Show runtime and provider status", "Session"),
    CommandSpec("/workspace", "Show or change the active workspace", "Session", True),
    CommandSpec("/model", "Show the active local model", "Session"),
    CommandSpec("/context", "Show bounded conversation context", "Session"),
    CommandSpec("/apps", "Browse discovered applications", "Work"),
    CommandSpec("/workflows", "Browse saved workflows", "Work"),
    CommandSpec("/tasks", "List durable tasks", "Work"),
    CommandSpec("/task", "Inspect one durable task", "Work", True),
    CommandSpec("/approvals", "Review pending approvals", "Work"),
    CommandSpec("/history", "Show durable session messages", "Conversation"),
    CommandSpec("/compact", "Bound the visible conversation context", "Conversation"),
    CommandSpec("/clear", "Start a new visible Mil session", "Conversation"),
    CommandSpec("/help", "Show command help", "System"),
    CommandSpec("/doctor", "Run the local runtime health check", "System"),
    CommandSpec("/stop", "Cancel the current client operation", "System"),
    CommandSpec("/exit", "End this Mil session", "System"),
    CommandSpec("/begin", "Enter multiline prompt mode", "Conversation"),
)


def command_specs() -> tuple[CommandSpec, ...]:
    return _COMMANDS


def filter_commands(prefix: str) -> tuple[CommandSpec, ...]:
    """Return commands matching a slash prefix, case-insensitively."""
    normalized = prefix.strip().casefold()
    if not normalized.startswith("/"):
        normalized = "/" + normalized
    return tuple(item for item in _COMMANDS if item.name.casefold().startswith(normalized))


def parse_command(line: str) -> tuple[CommandSpec | None, str]:
    """Split a command into metadata and its optional argument."""
    command, _, argument = line.strip().partition(" ")
    match = next((item for item in _COMMANDS if item.name == command.casefold()), None)
    return match, argument.strip()


def help_text() -> str:
    """Render concise grouped help without terminal-specific styling."""
    groups: list[str] = []
    for group in ("Session", "Work", "Conversation", "System"):
        entries = [item for item in _COMMANDS if item.group == group]
        groups.append(group)
        groups.extend(f"  {item.name:<12} {item.description}" for item in entries)
    groups.append("  /quit        Alias for /exit")
    groups.append("  /end         Finish /begin multiline mode")
    return "\n".join(groups)
