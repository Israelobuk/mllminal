"""Privacy-filtered semantic interaction capture with separate replay permission."""

import json
from pathlib import Path
from typing import Any, cast

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as DbSession

from mllminal.contracts import utc_now
from mllminal.interaction.contracts import (
    InteractionCaptureResult,
    InteractionEvent,
    InteractionKind,
    InteractionStatus,
    ReplayPlan,
)
from mllminal.interaction.persistence import (
    InteractionEventRow,
    InteractionIdempotencyRow,
    InteractionStateRow,
    load_event_rows,
)
from mllminal.persistence import Base
from mllminal.privacy.contracts import (
    CaptureCategory,
    CaptureContext,
    CaptureRequest,
    SensitiveControlClassification,
)
from mllminal.privacy.service import PrivacyService


class InteractionService:
    def __init__(self, database_path: Path, privacy: PrivacyService) -> None:
        self.database_path = database_path
        self.privacy = privacy
        self.engine = create_engine(f"sqlite:///{database_path}")
        Base.metadata.create_all(self.engine)
        self._initialize_state()

    def _initialize_state(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with DbSession(self.engine) as database, database.begin():
            if database.get(InteractionStateRow, 1) is None:
                database.add(
                    InteractionStateRow(id=1, replay_authorized=False, updated_at=utc_now())
                )

    def status(self) -> InteractionStatus:
        privacy_status = self.privacy.status()
        with DbSession(self.engine) as database:
            state = database.get(InteractionStateRow, 1)
            count = len(list(database.scalars(select(InteractionEventRow))))
            observing = privacy_status.observation_enabled and privacy_status.consent_granted
            if privacy_status.emergency_stop_active:
                visible = "EMERGENCY STOP"
            elif privacy_status.paused:
                visible = "OBSERVATION PAUSED"
            elif privacy_status.incognito_active:
                visible = "OBSERVATION INCOGNITO"
            else:
                visible = "OBSERVATION ON" if observing else "OBSERVATION OFF"
            return InteractionStatus(
                observation_enabled=observing,
                capture_visible=True,
                visible_status=visible,
                replay_authorized=bool(state and state.replay_authorized),
                event_count=count,
            )

    def authorize_replay(self, *, idempotency_key: str) -> InteractionStatus:
        def action(database: DbSession) -> InteractionStatus:
            state = database.get(InteractionStateRow, 1)
            if state is None:
                raise RuntimeError("Interaction state has not been initialized")
            state.replay_authorized = True
            state.updated_at = utc_now()
            return self._status_in(database)

        return self._mutate(idempotency_key, "replay.authorize", action)

    def revoke_replay(self, *, idempotency_key: str) -> InteractionStatus:
        def action(database: DbSession) -> InteractionStatus:
            state = database.get(InteractionStateRow, 1)
            if state is None:
                raise RuntimeError("Interaction state has not been initialized")
            state.replay_authorized = False
            state.updated_at = utc_now()
            return self._status_in(database)

        return self._mutate(idempotency_key, "replay.revoke", action)

    def capture(self, event: InteractionEvent, *, idempotency_key: str) -> InteractionCaptureResult:
        cached = self._cached(idempotency_key, "capture")
        if cached is not None:
            return InteractionCaptureResult.model_validate(cached)
        category = self._category(event)
        stored_event = event
        if category is CaptureCategory.SEMANTIC_POINTER:
            stored_event = event.model_copy(update={"pointer": None})
        elif category is CaptureCategory.RAW_COORDINATES:
            stored_event = event.model_copy(update={"replayable": False})
        context = self._context(event)
        privacy_result = self.privacy.capture(
            CaptureRequest(
                category=category,
                payload=stored_event.model_dump(mode="json"),
                context=context,
            ),
            idempotency_key=f"interaction:{idempotency_key}",
        )
        result = InteractionCaptureResult(
            accepted=privacy_result.accepted,
            reason=privacy_result.decision.reason,
            privacy_decision=privacy_result.decision,
            event=stored_event if privacy_result.accepted else None,
        )
        if privacy_result.accepted:
            with DbSession(self.engine) as database, database.begin():
                database.add(
                    InteractionEventRow(
                        id=stored_event.id,
                        kind=stored_event.kind.value,
                        payload_json=stored_event.model_dump_json(),
                        replayable=stored_event.replayable,
                        created_at=stored_event.created_at,
                    )
                )
        with DbSession(self.engine) as database, database.begin():
            database.add(
                InteractionIdempotencyRow(
                    key=idempotency_key,
                    operation="capture",
                    result_json=result.model_dump_json(),
                    created_at=utc_now(),
                )
            )
        return result

    def events(self) -> list[InteractionEvent]:
        with DbSession(self.engine) as database:
            return [
                InteractionEvent.model_validate_json(row.payload_json)
                for row in load_event_rows(database)
            ]

    def prepare_replay(self, event_id: str, *, idempotency_key: str) -> ReplayPlan:
        cached = self._cached(idempotency_key, "replay.prepare")
        if cached is not None:
            return ReplayPlan.model_validate(cached)
        if not self.status().replay_authorized:
            raise PermissionError("Separate replay permission is required")
        with DbSession(self.engine) as database:
            row = database.get(InteractionEventRow, event_id)
            if row is None:
                raise KeyError(event_id)
            event = InteractionEvent.model_validate_json(row.payload_json)
        if not event.replayable:
            raise PermissionError("Coordinate-only interaction is diagnostic and not replayable")
        plan = ReplayPlan(event=event)
        with DbSession(self.engine) as database, database.begin():
            database.add(
                InteractionIdempotencyRow(
                    key=idempotency_key,
                    operation="replay.prepare",
                    result_json=plan.model_dump_json(),
                    created_at=utc_now(),
                )
            )
        return plan

    @staticmethod
    def _category(event: InteractionEvent) -> CaptureCategory:
        if event.kind in {
            InteractionKind.APPLICATION_FOCUSED,
            InteractionKind.WINDOW_FOCUSED,
            InteractionKind.FILE_OPERATION,
        }:
            return CaptureCategory.DEVICE_METADATA
        if event.kind in {
            InteractionKind.KEYBOARD_SHORTCUT,
            InteractionKind.KEYBOARD_NAVIGATION,
            InteractionKind.KEYBOARD_CONFIRM,
            InteractionKind.KEYBOARD_CANCEL,
            InteractionKind.KEYBOARD_TAB,
            InteractionKind.KEYBOARD_COPY,
            InteractionKind.KEYBOARD_PASTE,
        }:
            return CaptureCategory.KEYBOARD_SHORTCUTS
        if event.kind in {InteractionKind.TEXT_ENTRY_STARTED, InteractionKind.TEXT_ENTRY_COMPLETED}:
            return CaptureCategory.TEXT_ENTRY_METADATA
        if event.target is not None:
            return CaptureCategory.SEMANTIC_POINTER
        return CaptureCategory.RAW_COORDINATES

    @staticmethod
    def _context(event: InteractionEvent) -> CaptureContext:
        application = event.target.application if event.target else None
        secure = (
            event.text_metadata.secure_control
            if event.text_metadata
            else SensitiveControlClassification.NONE
        )
        if secure is SensitiveControlClassification.NONE and event.text_metadata is not None:
            classification = event.text_metadata.field_classification.lower().replace("-", "_")
            sensitive_fields = {
                "secure": SensitiveControlClassification.SECURE,
                "password": SensitiveControlClassification.PASSWORD,
                "pin": SensitiveControlClassification.PIN,
                "recovery_code": SensitiveControlClassification.RECOVERY_CODE,
                "authentication_token": SensitiveControlClassification.AUTHENTICATION_TOKEN,
                "payment_card": SensitiveControlClassification.PAYMENT_CARD,
                "credential_prompt": SensitiveControlClassification.CREDENTIAL_PROMPT,
                "password_manager": SensitiveControlClassification.PASSWORD_MANAGER,
                "private_browser_password": SensitiveControlClassification.PASSWORD,
            }
            for marker, sensitive in sensitive_fields.items():
                if marker in classification:
                    secure = sensitive
                    break
        return CaptureContext(application=application, secure_control=secure, adapter="interaction")

    def _status_in(self, database: DbSession) -> InteractionStatus:
        state = database.get(InteractionStateRow, 1)
        privacy_status = self.privacy.status()
        observing = privacy_status.observation_enabled and privacy_status.consent_granted
        return InteractionStatus(
            observation_enabled=observing,
            capture_visible=True,
            visible_status="OBSERVATION ON" if observing else "OBSERVATION OFF",
            replay_authorized=bool(state and state.replay_authorized),
            event_count=len(list(database.scalars(select(InteractionEventRow)))),
        )

    def _cached(self, key: str, operation: str) -> dict[str, Any] | None:
        with DbSession(self.engine) as database:
            row = database.get(InteractionIdempotencyRow, key)
            if row is None:
                return None
            if row.operation != operation:
                raise ValueError("Idempotency key was already used for a different operation")
            return cast(dict[str, Any], json.loads(row.result_json))

    def _mutate(self, key: str, operation: str, action: Any) -> InteractionStatus:
        cached = self._cached(key, operation)
        if cached is not None:
            return InteractionStatus.model_validate(cached)
        with DbSession(self.engine) as database, database.begin():
            result = cast(InteractionStatus, action(database))
            database.add(
                InteractionIdempotencyRow(
                    key=key,
                    operation=operation,
                    result_json=result.model_dump_json(),
                    created_at=utc_now(),
                )
            )
            return result
