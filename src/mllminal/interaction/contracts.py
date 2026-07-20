"""Versioned contracts for semantic interaction observation."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, field_validator, model_validator

from mllminal.contracts import Contract, new_id, utc_now
from mllminal.privacy.contracts import PrivacyDecision, SensitiveControlClassification


class InteractionKind(StrEnum):
    CONTROL_INVOKED = "control.invoked"
    APPLICATION_FOCUSED = "application.focused"
    WINDOW_FOCUSED = "window.focused"
    FILE_OPERATION = "file.operation"
    MOUSE_CLICK = "mouse.click"
    MOUSE_DOUBLE_CLICK = "mouse.double_click"
    MOUSE_SCROLL = "mouse.scroll"
    MOUSE_DRAG = "mouse.drag"
    KEYBOARD_SHORTCUT = "keyboard.shortcut"
    KEYBOARD_NAVIGATION = "keyboard.navigation"
    KEYBOARD_CONFIRM = "keyboard.confirm"
    KEYBOARD_CANCEL = "keyboard.cancel"
    KEYBOARD_TAB = "keyboard.tab"
    KEYBOARD_COPY = "keyboard.copy"
    KEYBOARD_PASTE = "keyboard.paste"
    TEXT_ENTRY_STARTED = "text_entry.started"
    TEXT_ENTRY_COMPLETED = "text_entry.completed"


class NavigationKey(StrEnum):
    TAB = "TAB"
    SHIFT_TAB = "SHIFT+TAB"
    ARROW_UP = "ARROW_UP"
    ARROW_DOWN = "ARROW_DOWN"
    ARROW_LEFT = "ARROW_LEFT"
    ARROW_RIGHT = "ARROW_RIGHT"
    HOME = "HOME"
    END = "END"
    PAGE_UP = "PAGE_UP"
    PAGE_DOWN = "PAGE_DOWN"


class SemanticTarget(Contract):
    application: str
    window: str | None = None
    control_role: str | None = None
    control_name: str | None = None
    automation_id: str | None = None
    action_type: str = "invoke"


class PointerMetadata(Contract):
    x: float | None = None
    y: float | None = None
    button: str | None = None
    delta_x: float | None = None
    delta_y: float | None = None
    amount_bucket: str | None = None


class TextEntryMetadata(Contract):
    field_classification: str
    length_bucket: str
    correction_count: int = Field(default=0, ge=0)
    paste: bool = False
    completed: bool = False
    secure_control: SensitiveControlClassification = SensitiveControlClassification.NONE


class InteractionEvent(Contract):
    id: str = Field(default_factory=new_id)
    kind: InteractionKind
    target: SemanticTarget | None = None
    pointer: PointerMetadata | None = None
    shortcut: str | None = None
    navigation_key: NavigationKey | None = None
    text_metadata: TextEntryMetadata | None = None
    replayable: bool = True
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("shortcut")
    @classmethod
    def normalize_shortcut(cls, value: str | None) -> str | None:
        return "+".join(part.strip().upper() for part in value.split("+")) if value else value

    @model_validator(mode="after")
    def validate_shape(self) -> "InteractionEvent":
        if self.kind is InteractionKind.CONTROL_INVOKED and self.target is None:
            raise ValueError("control.invoked requires a semantic target")
        if (
            self.kind
            in {
                InteractionKind.KEYBOARD_SHORTCUT,
                InteractionKind.KEYBOARD_CONFIRM,
                InteractionKind.KEYBOARD_CANCEL,
                InteractionKind.KEYBOARD_TAB,
                InteractionKind.KEYBOARD_COPY,
                InteractionKind.KEYBOARD_PASTE,
            }
            and not self.shortcut
        ):
            raise ValueError(f"{self.kind} requires a semantic shortcut")
        if self.kind is InteractionKind.KEYBOARD_NAVIGATION and self.navigation_key is None:
            raise ValueError("keyboard.navigation requires a navigation key")
        if (
            self.kind
            in {
                InteractionKind.TEXT_ENTRY_STARTED,
                InteractionKind.TEXT_ENTRY_COMPLETED,
            }
            and self.text_metadata is None
        ):
            raise ValueError(f"{self.kind} requires text-entry metadata")
        if (
            self.kind
            in {
                InteractionKind.MOUSE_CLICK,
                InteractionKind.MOUSE_DOUBLE_CLICK,
                InteractionKind.MOUSE_SCROLL,
                InteractionKind.MOUSE_DRAG,
            }
            and self.target is None
            and self.pointer is None
        ):
            raise ValueError(f"{self.kind} requires a semantic target or pointer metadata")
        return self


class InteractionStatus(Contract):
    observation_enabled: bool
    capture_visible: bool
    visible_status: str
    replay_authorized: bool
    event_count: int = Field(ge=0)


class InteractionCaptureResult(Contract):
    accepted: bool
    reason: str
    privacy_decision: PrivacyDecision
    event: InteractionEvent | None = None


class ReplayPlan(Contract):
    event: InteractionEvent
    authorized: bool = True
    execution_mode: str = "typed_replay_preview"


class InteractionEventPayload(Contract):
    """Typed wire payload helper for clients that need a generic dictionary."""

    values: dict[str, Any]
