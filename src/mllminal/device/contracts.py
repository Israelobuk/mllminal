"""Versioned, metadata-only device observer contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, Self
from uuid6 import uuid7

from pydantic import BaseModel, ConfigDict, Field, model_validator

_DEVICE_EVENTS = {
    "application.started", "application.exited", "application.focused",
    "window.opened", "window.closed", "window.focused", "window.title_changed",
    "control.focused", "mouse.click", "mouse.double_click", "mouse.scroll",
    "keyboard.shortcut", "keyboard.navigation", "keyboard.confirm", "keyboard.cancel",
    "keyboard.tab", "file.created", "file.modified", "file.moved", "file.renamed",
    "file.deleted", "user.active", "user.idle", "observer.started", "observer.stopped",
    "observer.paused", "observer.resumed",
}
_FORBIDDEN = {
    "typed_text", "password", "clipboard", "token", "screenshot", "audio", "camera", "keystroke",
}


class ApplicationIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    process_name: str
    application_class: str = "unknown"
    executable_path: str | None = None
    executable_hash: str | None = None
    publisher: str | None = None


class WindowIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    title_classification: str = "unknown"
    title_redacted: bool = True
    window_class: str = "unknown"


class ControlIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    control_type: str = "unknown"
    automation_id: str | None = None
    class_name: str = "unknown"
    secure: bool = False


class RawDeviceSignal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    event_type: str
    source: str
    timestamp: datetime
    payload: dict[str, Any]

    @model_validator(mode="after")
    def validate_safe_payload(self) -> Self:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() != UTC.utcoffset(self.timestamp):
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
    window: WindowIdentity | None = None
    control: ControlIdentity | None = None


def normalize_signal(signal: RawDeviceSignal) -> NormalizedDeviceEvent:
    if signal.event_type not in _DEVICE_EVENTS:
        raise ValueError("unsupported device event type")
    payload = signal.payload
    application = None
    if "process_name" in payload:
        application = ApplicationIdentity(
            process_name=str(payload["process_name"]),
            application_class=str(payload.get("application_class") or "unknown"),
            executable_path=(str(payload["executable_path"]) if payload.get("executable_path") else None),
            publisher=str(payload["publisher"]) if payload.get("publisher") else None,
        )
    window = None
    if {"title", "title_classification", "window_class"} & payload.keys():
        window = WindowIdentity(
            title_classification=str(payload.get("title_classification") or "document"),
            window_class=str(payload.get("window_class") or "unknown"),
        )
    control = None
    if "control_type" in payload:
        control = ControlIdentity(
            control_type=str(payload.get("control_type") or "unknown"),
            automation_id=(str(payload["automation_id"]) if payload.get("automation_id") else None),
            class_name=str(payload.get("class_name") or "unknown"),
            secure=bool(payload.get("secure", False)),
        )
    return NormalizedDeviceEvent(
        event_type=signal.event_type,
        timestamp=signal.timestamp,
        source=signal.source,
        application=application,
        window=window,
        control=control,
    )
