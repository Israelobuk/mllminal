"""Planner envelope instructions, version 1."""


def planner_message() -> str:
    return """Return JSON with response and plan fields. Plan steps must use only
registered tools with typed arguments. Do not include tool results or claims that work ran."""
