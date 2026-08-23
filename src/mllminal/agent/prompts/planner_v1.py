"""Planner envelope instructions, version 1."""


def planner_message() -> str:
    return """Return only JSON, with no Markdown fences, commentary, or hidden reasoning.
Use the exact response_schema supplied below. Plan steps must use only tools in the
supplied registry with typed arguments. Do not include tool results or claims that work ran."""
