"""Workspace-safe slash, mention, and file completion for Mil prompts."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document

from mllminal.client.interactive.commands import filter_commands


@dataclass(frozen=True, slots=True)
class ContextResource:
    label: str
    kind: str
    value: str


class MilCompleter(Completer):
    """Complete only resources supplied by the daemon or inside the workspace."""

    def __init__(self, workspace: Path, resources: Iterable[ContextResource] = ()) -> None:
        self.workspace = workspace.resolve()
        self.resources = tuple(resources)

    def get_completions(self, document: Document, complete_event: object) -> Iterable[Completion]:
        del complete_event
        token = document.text_before_cursor.rsplit(None, 1)[-1]
        if token.startswith("/"):
            yield from (
                Completion(
                    item.name,
                    start_position=-len(token),
                    display=item.name,
                    display_meta=item.description,
                )
                for item in filter_commands(token)
            )
            return
        if token.startswith("@"):
            yield from (
                Completion(
                    f"@{item.value}",
                    start_position=-len(token),
                    display=f"@{item.label}",
                    display_meta=item.kind,
                )
                for item in self.resources
                if item.value.casefold().startswith(token[1:].casefold())
                or item.label.casefold().startswith(token[1:].casefold())
            )
            return
        if self._looks_like_path(token):
            yield from self._path_completions(token)

    def _path_completions(self, token: str) -> Iterable[Completion]:
        path = Path(token)
        if path.is_absolute() or ".." in path.parts:
            return
        parent = self._safe_path(self.workspace / path.parent)
        if parent is None or not parent.is_dir():
            return
        prefix = path.name.casefold()
        for candidate in sorted(parent.iterdir(), key=lambda item: item.name.casefold()):
            if not candidate.name.casefold().startswith(prefix):
                continue
            relative = candidate.relative_to(self.workspace).as_posix()
            if token.startswith("./"):
                relative = "./" + relative
            if candidate.is_dir():
                relative += "/"
            yield Completion(relative, start_position=-len(token), display=relative)

    @staticmethod
    def _looks_like_path(token: str) -> bool:
        return token.startswith(("./", ".\\", "../", "..\\")) or "/" in token or "\\" in token

    def _safe_path(self, candidate: Path) -> Path | None:
        try:
            resolved = candidate.resolve()
        except OSError:
            return None
        try:
            resolved.relative_to(self.workspace)
        except ValueError:
            return None
        return resolved
