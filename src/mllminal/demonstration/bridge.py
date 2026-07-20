"""Bridge real normalized device events into an inactive demonstration draft."""

from __future__ import annotations

import logging
from typing import Any

from mllminal.demonstration.contracts import DemonstrationCaptureRequest
from mllminal.demonstration.service import DemonstrationService
from mllminal.device.contracts import NormalizedDeviceEvent
from mllminal.interaction.contracts import (
    InteractionEvent,
    InteractionKind,
    NavigationKey,
    PointerMetadata,
    SemanticTarget,
    TextEntryMetadata,
)

logger = logging.getLogger(__name__)


class DeviceDemonstrationBridge:
    """Convert only privacy-normalized observer events while a session is recording."""

    def __init__(self, demonstration: DemonstrationService) -> None:
        self.demonstration = demonstration

    def handle(self, device_event: NormalizedDeviceEvent) -> None:
        status = self.demonstration.status()
        session = status.session
        if session is None or not status.recording:
            return
        converted = self._convert(device_event)
        if converted is None:
            return
        event, file_operation, application_transition, text_entry, fragile = converted
        request = DemonstrationCaptureRequest(
            event=event,
            normalized_file_operation=file_operation,
            application_transition=application_transition,
            text_entry_occurred=text_entry,
            fragile=fragile,
            source_event_id=device_event.event_id,
        )
        try:
            self.demonstration.record(
                session.id,
                request,
                idempotency_key=f"device-demonstration:{session.id}:{device_event.event_id}",
            )
        except Exception:
            logger.exception("real device event could not be added to demonstration")

    def _convert(
        self, device_event: NormalizedDeviceEvent
    ) -> tuple[InteractionEvent, str | None, str | None, bool, bool] | None:
        target = self._target(device_event)
        event_type = device_event.event_type
        metadata = device_event.metadata
        created_at = device_event.timestamp

        if event_type == "application.focused":
            if target is None:
                return None
            return (
                InteractionEvent(
                    kind=InteractionKind.APPLICATION_FOCUSED,
                    target=target,
                    replayable=False,
                    created_at=created_at,
                ),
                None,
                target.application,
                False,
                False,
            )
        if event_type == "window.focused":
            if target is None:
                return None
            return (
                InteractionEvent(
                    kind=InteractionKind.WINDOW_FOCUSED,
                    target=target,
                    replayable=False,
                    created_at=created_at,
                ),
                None,
                target.application,
                False,
                False,
            )
        if event_type == "control.invoked":
            if target is None or device_event.control is None or device_event.control.secure:
                return None
            pointer = (
                PointerMetadata(button=str(metadata["button"])) if metadata.get("button") else None
            )
            return (
                InteractionEvent(
                    kind=InteractionKind.CONTROL_INVOKED,
                    target=target,
                    pointer=pointer,
                    replayable=True,
                    created_at=created_at,
                ),
                None,
                None,
                False,
                False,
            )
        if event_type in {"mouse.click", "mouse.double_click"}:
            kind = (
                InteractionKind.MOUSE_DOUBLE_CLICK
                if event_type == "mouse.double_click"
                else InteractionKind.MOUSE_CLICK
            )
            pointer = PointerMetadata(
                button=str(metadata["button"]) if metadata.get("button") else None
            )
            return (
                InteractionEvent(
                    kind=kind,
                    target=target,
                    pointer=pointer,
                    replayable=target is not None and device_event.control is not None,
                    created_at=created_at,
                ),
                None,
                None,
                False,
                device_event.control is None,
            )
        if event_type == "mouse.scroll":
            direction = str(metadata.get("direction") or "down")
            pointer = PointerMetadata(
                delta_y=-1.0 if direction == "up" else 1.0,
                amount_bucket=(
                    str(metadata["amount_bucket"]) if metadata.get("amount_bucket") else None
                ),
            )
            return (
                InteractionEvent(
                    kind=InteractionKind.MOUSE_SCROLL,
                    target=target,
                    pointer=pointer,
                    replayable=False,
                    created_at=created_at,
                ),
                None,
                None,
                False,
                target is None,
            )
        if event_type in {
            "keyboard.shortcut",
            "keyboard.confirm",
            "keyboard.cancel",
            "keyboard.tab",
        }:
            shortcut = str(metadata.get("shortcut") or self._shortcut_for(event_type, metadata))
            return (
                InteractionEvent(
                    kind={
                        "keyboard.shortcut": InteractionKind.KEYBOARD_SHORTCUT,
                        "keyboard.confirm": InteractionKind.KEYBOARD_CONFIRM,
                        "keyboard.cancel": InteractionKind.KEYBOARD_CANCEL,
                        "keyboard.tab": InteractionKind.KEYBOARD_TAB,
                    }[event_type],
                    shortcut=shortcut,
                    target=target,
                    replayable=True,
                    created_at=created_at,
                ),
                None,
                None,
                False,
                False,
            )
        if event_type == "keyboard.navigation":
            key = self._navigation_key(str(metadata.get("key_role") or ""), metadata)
            if key is None:
                return None
            return (
                InteractionEvent(
                    kind=InteractionKind.KEYBOARD_NAVIGATION,
                    navigation_key=key,
                    target=target,
                    replayable=True,
                    created_at=created_at,
                ),
                None,
                None,
                False,
                False,
            )
        if event_type == "text_entry.started":
            if device_event.control is not None and device_event.control.secure:
                return None
            return (
                InteractionEvent(
                    kind=InteractionKind.TEXT_ENTRY_STARTED,
                    target=target,
                    text_metadata=TextEntryMetadata(
                        field_classification=str(metadata.get("field_classification") or "text"),
                        length_bucket=str(metadata.get("length_bucket") or "unknown"),
                    ),
                    replayable=False,
                    created_at=created_at,
                ),
                None,
                None,
                True,
                False,
            )
        if event_type.startswith("file."):
            return (
                InteractionEvent(
                    kind=InteractionKind.FILE_OPERATION,
                    target=SemanticTarget(
                        application="filesystem",
                        action_type=event_type,
                    ),
                    replayable=False,
                    created_at=created_at,
                ),
                event_type,
                None,
                False,
                False,
            )
        return None

    @staticmethod
    def _target(device_event: NormalizedDeviceEvent) -> SemanticTarget | None:
        application = device_event.application.process_name if device_event.application else None
        if application is None and device_event.control is None:
            return None
        control = device_event.control
        return SemanticTarget(
            application=application or "unknown",
            window=(device_event.window.title_classification if device_event.window else None),
            control_role=control.control_type if control else None,
            control_name=control.name if control and not control.secure else None,
            automation_id=control.automation_id if control else None,
        )

    @staticmethod
    def _shortcut_for(event_type: str, metadata: dict[str, Any]) -> str:
        if event_type == "keyboard.confirm":
            return "ENTER"
        if event_type == "keyboard.cancel":
            return "ESC"
        if event_type == "keyboard.tab":
            return "SHIFT+TAB" if metadata.get("reverse") else "TAB"
        return "UNKNOWN"

    @staticmethod
    def _navigation_key(role: str, metadata: dict[str, Any]) -> NavigationKey | None:
        values = {
            "tab": NavigationKey.SHIFT_TAB if metadata.get("reverse") else NavigationKey.TAB,
            "left": NavigationKey.ARROW_LEFT,
            "right": NavigationKey.ARROW_RIGHT,
            "up": NavigationKey.ARROW_UP,
            "down": NavigationKey.ARROW_DOWN,
            "home": NavigationKey.HOME,
            "end": NavigationKey.END,
            "page_up": NavigationKey.PAGE_UP,
            "page_down": NavigationKey.PAGE_DOWN,
        }
        return values.get(role)
