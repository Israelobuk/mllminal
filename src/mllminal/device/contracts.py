"""Versioned, metadata-only device observer contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from uuid6 import uuid7

_DEVICE_EVENTS = {
    "application.started",
    "application.exited",
    "application.focused",
    "window.opened",
    "window.closed",
    "window.focused",
    "window.title_changed",
    "file.created",
    "file.modified",
    "file.moved",
    "file.renamed",
    "file.deleted",
    "user.active",
    "user.idle",
    "observer.started",
    "observer.stopped",
    "observer.paused",
    "observer.resumed",
}
_FORBIDDEN = {
    "typed_text",
    "password",
    "clipboard",
    "token",
    "screenshot",
    "audio",
    "camera",
    "keystroke",
}


class ApplicationIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    process_name: str
    application_class: str = "unknown"
    executable_hash: str | None = None
    publisher: str | None = None


class RawDeviceSignal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    event_type: str
    source: str
    timestamp: datetime
    payload: dict[str, Any]

    @model_validator(mode="after")
    def validate_safe_payload(self) -> Self:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() != UTC.utcoffset(
            self.timestamp
        ):
            raise ValueError("timestamp must be UTC")
        if _FORBIDDEN & {key.lower() for key in self.payload}:
            raise ValueError("forbidden raw payload field")
        return self


class NormalizedDeviceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    event_id: str = Field(default_factory=lambda: str(uuid7()))
    schema_version: Literal["1"] = "1"
    event_type: str
    timestamp: datetime
    source: str
    monotonic_sequence: int = Field(default=0, ge=0)
    application: ApplicationIdentity | None = None


def normalize_signal(signal: RawDeviceSignal) -> NormalizedDeviceEvent:
    if signal.event_type not in _DEVICE_EVENTS:
        raise ValueError("unsupported device event type")
    payload = signal.payload
    application = None
    if "process_name" in payload:
        application = ApplicationIdentity(
            process_name=str(payload["process_name"]),
            publisher=str(payload["publisher"]) if payload.get("publisher") else None,
        )
    return NormalizedDeviceEvent(
        event_type=signal.event_type,
        timestamp=signal.timestamp,
        source=signal.source,
        application=application,
    )
