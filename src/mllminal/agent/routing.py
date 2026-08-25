"""Deterministic routing for Mil's conversational and execution paths."""

import re
from enum import StrEnum


class MilRoute(StrEnum):
    """The smallest set of behavior modes exposed by the Mil runtime."""

    CHAT = "chat"
    LOCAL_INFORMATION = "local_information"
    READ_ONLY_TOOL = "read_only_tool"
    ACTION = "action"
    WORKFLOW = "workflow"
    DESTRUCTIVE_ACTION = "destructive_action"


_WORD = re.compile(r"[a-z0-9']+")

_LOCAL_INFORMATION = {
    "daemon",
    "endpoint",
    "model",
    "app",
    "apps",
    "application",
    "applications",
    "provider",
    "ready",
    "service",
    "status",
    "workspace",
}
_READ_ONLY = {
    "count",
    "find",
    "inspect",
    "list",
    "read",
    "scan",
    "show",
    "summarize",
}
_READ_ONLY_TARGETS = {
    "document",
    "file",
    "files",
    "folder",
    "project",
    "readme",
    "report",
    "workspace",
}
_WORKFLOW = {"automate", "automation", "workflow", "workflows", "repeat"}
_DESTRUCTIVE = {
    "delete",
    "destroy",
    "erase",
    "purge",
    "remove",
    "send",
    "submit",
}
_ACTION = {
    "click",
    "create",
    "launch",
    "move",
    "open",
    "save",
    "write",
}


def route_request(request: str) -> MilRoute:
    """Classify a request without invoking a model, tool, or task store."""
    words = set(_WORD.findall(request.casefold()))
    if not words:
        return MilRoute.CHAT
    if (
        "open" in words
        and words & {"app", "apps", "application", "applications"}
        and words & {"are", "is", "what", "which"}
    ):
        return MilRoute.LOCAL_INFORMATION
    if words & _DESTRUCTIVE:
        return MilRoute.DESTRUCTIVE_ACTION
    if words & _WORKFLOW:
        return MilRoute.WORKFLOW
    if words & _READ_ONLY and words & _READ_ONLY_TARGETS:
        return MilRoute.READ_ONLY_TOOL
    if words & _ACTION:
        return MilRoute.ACTION
    if words & _LOCAL_INFORMATION:
        return MilRoute.LOCAL_INFORMATION
    return MilRoute.CHAT
