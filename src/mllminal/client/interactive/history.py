"""Local, bounded, privacy-aware prompt history for interactive Mil."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from prompt_toolkit.history import History


class LocalPromptHistory(History):
    """Persist non-sensitive prompt strings without touching daemon history."""

    _SENSITIVE_MARKERS = (
        "password",
        "passwd",
        "secret",
        "api key",
        "apikey",
        "token",
        "cookie",
        "credential",
        "private key",
    )

    def __init__(self, path: Path, *, enabled: bool = True, max_entries: int = 100) -> None:
        super().__init__()
        self.path = path
        self.enabled = enabled
        self.max_entries = max(1, max_entries)
        self._loaded_strings = list(self.load_history_strings())[: self.max_entries]
        self._loaded = True

    def load_history_strings(self) -> Iterable[str]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        values: list[str] = []
        for line in reversed(lines):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and isinstance(value.get("prompt"), str):
                values.append(value["prompt"])
        return values

    def append_string(self, string: str) -> None:
        if self.enabled and self._safe(string):
            super().append_string(string)
            self._persist()

    def store_string(self, string: str) -> None:
        del string

    def _persist(self) -> None:
        if not self.enabled:
            return
        values = self.get_strings()[-self.max_entries :]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".next")
        temporary.write_text(
            "".join(json.dumps({"prompt": value}, ensure_ascii=False) + "\n" for value in values),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    @classmethod
    def _safe(cls, value: str) -> bool:
        normalized = value.casefold()
        return bool(value.strip()) and not any(
            marker in normalized for marker in cls._SENSITIVE_MARKERS
        )
