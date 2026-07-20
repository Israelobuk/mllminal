"""Bounded, metadata-only observer with deterministic and native adapters."""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from mllminal.device.contracts import NormalizedDeviceEvent, RawDeviceSignal, normalize_signal


@dataclass(frozen=True)
class ObserverStatus:
    state: str = "STOPPED"
    dropped_events: int = 0
    duplicate_events: int = 0


@dataclass(frozen=True)
class ObserverHealth:
    healthy: bool = True
    last_error: str | None = None


@dataclass(frozen=True)
class ObserverCapability:
    name: str
    available: bool
    metadata_only: bool = True


class DeviceAdapter(Protocol):
    name: str

    def poll(self) -> list[RawDeviceSignal]: ...

    def capability(self) -> ObserverCapability: ...


class FakeDeviceAdapter:
    def __init__(
        self,
        name: str,
        signals: list[RawDeviceSignal] | None = None,
        failure: Exception | None = None,
    ) -> None:
        self.name, self.signals, self.failure = name, signals or [], failure

    def capability(self) -> ObserverCapability:
        return ObserverCapability(self.name, True)

    def poll(self) -> list[RawDeviceSignal]:
        if self.failure:
            raise self.failure
        signals, self.signals = self.signals, []
        return signals


class DeviceObserver:
    def __init__(
        self, data_dir: Path, adapters: list[DeviceAdapter], queue_capacity: int = 256
    ) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.adapters = adapters
        self.queue: deque[NormalizedDeviceEvent] = deque(maxlen=queue_capacity)
        self.capacity = queue_capacity
        self._subscribers: list[Callable[[NormalizedDeviceEvent], None]] = []
        self._fingerprints: set[str] = set()
        self._events = self._load_events()
        self._sequence = max((e.monotonic_sequence for e in self._events), default=0)
        self.status = ObserverStatus()
        self._health = {adapter.name: ObserverHealth() for adapter in adapters}
        self._load_state()

    def start(self) -> None:
        self.status = ObserverStatus(
            "RUNNING", self.status.dropped_events, self.status.duplicate_events
        )
        self._save_state()

    def stop(self) -> None:
        self.status = ObserverStatus(
            "STOPPED", self.status.dropped_events, self.status.duplicate_events
        )
        self._save_state()

    def pause(self) -> None:
        self.status = ObserverStatus(
            "PAUSED", self.status.dropped_events, self.status.duplicate_events
        )
        self._save_state()

    def resume(self) -> None:
        self.start()

    def capabilities(self) -> list[ObserverCapability]:
        return [adapter.capability() for adapter in self.adapters]

    def health(self) -> dict[str, ObserverHealth]:
        return dict(self._health)

    def events(self) -> list[NormalizedDeviceEvent]:
        return list(self._events)

    def subscribe(self, callback: Callable[[NormalizedDeviceEvent], None]) -> None:
        self._subscribers.append(callback)

    def ingest(self, signal: RawDeviceSignal) -> bool:
        if self.status.state != "RUNNING":
            return False
        event = normalize_signal(signal)
        fingerprint = json.dumps(
            event.model_dump(mode="json", exclude={"event_id", "monotonic_sequence"}),
            sort_keys=True,
            separators=(",", ":"),
        )
        if fingerprint in self._fingerprints:
            self.status = ObserverStatus(
                self.status.state, self.status.dropped_events, self.status.duplicate_events + 1
            )
            self._save_state()
            return False
        if len(self.queue) >= self.capacity:
            self.status = ObserverStatus(
                self.status.state, self.status.dropped_events + 1, self.status.duplicate_events
            )
            self._save_state()
            return False
        self._fingerprints.add(fingerprint)
        self.queue.append(event)
        return True

    def poll(self) -> None:
        if self.status.state != "RUNNING":
            return
        for adapter in self.adapters:
            try:
                for signal in adapter.poll():
                    self.ingest(signal)
                self._health[adapter.name] = ObserverHealth()
            except Exception as error:
                self._health[adapter.name] = ObserverHealth(False, str(error))
                self._save_state()

    def drain(self) -> None:
        while self.queue:
            raw = self.queue.popleft()
            self._sequence += 1
            event = raw.model_copy(update={"monotonic_sequence": self._sequence})
            with (self.data_dir / "device-events.jsonl").open("a", encoding="utf-8") as out:
                out.write(event.model_dump_json() + "\n")
            self._events.append(event)
            for subscriber in self._subscribers:
                subscriber(event)
        self._save_state()

    def _load_events(self) -> list[NormalizedDeviceEvent]:
        path = self.data_dir / "device-events.jsonl"
        return (
            [
                NormalizedDeviceEvent.model_validate_json(line)
                for line in path.read_text(encoding="utf-8").splitlines()
            ]
            if path.exists()
            else []
        )

    def _save_state(self) -> None:
        (self.data_dir / "observer-state.json").write_text(
            json.dumps(
                {
                    "status": asdict(self.status),
                    "health": {key: asdict(value) for key, value in self._health.items()},
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )

    def _load_state(self) -> None:
        path = self.data_dir / "observer-state.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            self.status = ObserverStatus(**data["status"])
            self._health = {key: ObserverHealth(**value) for key, value in data["health"].items()}
