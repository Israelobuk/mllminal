"""Optional Windows metadata adapters; no content capture or execution authority."""

from __future__ import annotations

from datetime import UTC, datetime
from importlib import import_module
from typing import Any

from mllminal.device.contracts import RawDeviceSignal
from mllminal.device.observer import ObserverCapability


def _signal(event_type: str, source: str, payload: dict[str, Any]) -> RawDeviceSignal:
    return RawDeviceSignal(
        event_type=event_type, source=source, timestamp=datetime.now(UTC), payload=payload
    )


class WindowsProcessAdapter:
    name = "windows.process"

    def __init__(self, psutil_module: Any | None = None) -> None:
        if psutil_module is None:
            try:
                psutil_module = import_module("psutil")
            except ImportError:
                psutil_module = None
        self.psutil = psutil_module
        self._known: set[int] = set()

    def capability(self) -> ObserverCapability:
        return ObserverCapability(self.name, self.psutil is not None)

    def poll(self) -> list[RawDeviceSignal]:
        if self.psutil is None:
            return []
        current = {
            int(process.info["pid"]): str(process.info.get("name") or "unknown")
            for process in self.psutil.process_iter(["pid", "name"])
        }
        events = [
            _signal("application.started", self.name, {"process_name": current[pid]})
            for pid in current
            if pid not in self._known
        ]
        events += [
            _signal("application.exited", self.name, {"process_name": "unknown"})
            for pid in self._known
            if pid not in current
        ]
        self._known = set(current)
        return events


class FakeWindowsAdapter:
    def __init__(self, name: str, batches: list[tuple[str, dict[str, Any]]]) -> None:
        self.name, self.batches = name, batches

    def capability(self) -> ObserverCapability:
        return ObserverCapability(self.name, True)

    def poll(self) -> list[RawDeviceSignal]:
        result: list[RawDeviceSignal] = []
        for kind, payload in self.batches:
            if kind == "process":
                result += [
                    _signal("application.started", self.name, {"process_name": name})
                    for name in payload.get("started", [])
                ]
                result += [
                    _signal("application.exited", self.name, {"process_name": name})
                    for name in payload.get("exited", [])
                ]
            elif kind == "foreground":
                safe = {key: value for key, value in payload.items() if key != "title"}
                result.append(_signal("application.focused", self.name, safe))
                if "title" in payload:
                    result.append(
                        _signal("window.title_changed", self.name, {**safe, "title": "redacted"})
                    )
            elif kind == "filesystem":
                result.append(
                    _signal(str(payload["event_type"]), self.name, {"process_name": "filesystem"})
                )
            elif kind == "idle":
                result.append(
                    _signal("user.idle" if payload.get("idle") else "user.active", self.name, {})
                )
        self.batches = []
        return result
