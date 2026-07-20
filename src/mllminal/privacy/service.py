"""Durable, consent-gated privacy policy enforcement."""

import fnmatch
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar, cast

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as DbSession

from mllminal.contracts import new_id, utc_now
from mllminal.persistence import Base
from mllminal.privacy.contracts import (
    CaptureCategory,
    CapturedRecord,
    CaptureMode,
    CaptureRequest,
    CaptureResult,
    ConsentRecord,
    EmergencyStopState,
    IncognitoSession,
    PrivacyAuditEvent,
    PrivacyDecision,
    PrivacyDecisionType,
    PrivacyPolicy,
    PrivacyRule,
    PrivacyRuleType,
    PrivacyStatus,
    SensitiveControlClassification,
)
from mllminal.privacy.persistence import (
    PrivacyEventRow,
    PrivacyHistoryRow,
    PrivacyIdempotencyRow,
    PrivacyRuleRow,
    PrivacyStateRow,
    get_state,
    list_rules,
)

T = TypeVar("T")


class PrivacyService:
    """Owns privacy state, filtering, minimized history, and replay events."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.engine = create_engine(f"sqlite:///{database_path}")
        Base.metadata.create_all(self.engine)
        self._initialize_state()

    def now(self) -> datetime:
        return utc_now()

    def _initialize_state(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with DbSession(self.engine) as database, database.begin():
            if database.get(PrivacyStateRow, 1) is None:
                database.add(
                    PrivacyStateRow(
                        id=1,
                        policy_json=PrivacyPolicy().model_dump_json(),
                        consent_json=None,
                        incognito_json=None,
                        emergency_json=EmergencyStopState().model_dump_json(),
                        updated_at=utc_now(),
                    )
                )

    def policy(self) -> PrivacyPolicy:
        with DbSession(self.engine) as database:
            return PrivacyPolicy.model_validate_json(get_state(database).policy_json)

    def status(self) -> PrivacyStatus:
        self._purge_expired()
        with DbSession(self.engine) as database:
            state = get_state(database)
            policy = PrivacyPolicy.model_validate_json(state.policy_json)
            consent = (
                ConsentRecord.model_validate_json(state.consent_json)
                if state.consent_json
                else None
            )
            emergency = EmergencyStopState.model_validate_json(state.emergency_json)
            incognito = (
                IncognitoSession.model_validate_json(state.incognito_json)
                if state.incognito_json
                else None
            )
            exclusions = database.scalars(
                select(PrivacyRuleRow).where(PrivacyRuleRow.enabled.is_(True))
            )
            return PrivacyStatus(
                observation_enabled=policy.observation_enabled,
                paused=policy.paused,
                consent_granted=consent is not None and consent.revoked_at is None,
                incognito_active=incognito is not None and incognito.ended_at is None,
                emergency_stop_active=emergency.active,
                capture_modes=policy.capture_modes,
                retention=policy.retention,
                exclusion_count=len(list(exclusions)),
            )

    def enable(self, *, idempotency_key: str) -> PrivacyStatus:
        def action(database: DbSession) -> PrivacyStatus:
            state = get_state(database)
            policy = PrivacyPolicy.model_validate_json(state.policy_json)
            modes = dict(policy.capture_modes)
            modes[CaptureCategory.DEVICE_METADATA] = CaptureMode.METADATA
            updated = policy.model_copy(
                update={"observation_enabled": True, "paused": False, "capture_modes": modes}
            )
            state.policy_json = updated.model_dump_json()
            state.consent_json = ConsentRecord(granted_at=utc_now()).model_dump_json()
            state.updated_at = utc_now()
            self._event(database, "privacy.enabled", {"observation_enabled": True})
            return self._status_in(database, state)

        return self._mutate(idempotency_key, "enable", action, PrivacyStatus)

    def disable(self, *, idempotency_key: str) -> PrivacyStatus:
        def action(database: DbSession) -> PrivacyStatus:
            state = get_state(database)
            policy = PrivacyPolicy.model_validate_json(state.policy_json)
            state.policy_json = policy.model_copy(
                update={"observation_enabled": False}
            ).model_dump_json()
            consent = (
                ConsentRecord.model_validate_json(state.consent_json)
                if state.consent_json
                else ConsentRecord()
            )
            state.consent_json = consent.model_copy(
                update={"revoked_at": utc_now()}
            ).model_dump_json()
            state.updated_at = utc_now()
            self._event(database, "privacy.disabled", {"observation_enabled": False})
            return self._status_in(database, state)

        return self._mutate(idempotency_key, "disable", action, PrivacyStatus)

    def pause(self, *, idempotency_key: str) -> PrivacyStatus:
        return self._set_paused(True, idempotency_key)

    def resume(self, *, idempotency_key: str) -> PrivacyStatus:
        return self._set_paused(False, idempotency_key)

    def _set_paused(self, paused: bool, key: str) -> PrivacyStatus:
        def action(database: DbSession) -> PrivacyStatus:
            state = get_state(database)
            policy = PrivacyPolicy.model_validate_json(state.policy_json)
            updated = policy.model_copy(update={"paused": paused})
            state.policy_json = updated.model_dump_json()
            state.updated_at = utc_now()
            self._event(
                database, "privacy.paused" if paused else "privacy.resumed", {"paused": paused}
            )
            return self._status_in(database, state)

        return self._mutate(key, "pause" if paused else "resume", action, PrivacyStatus)

    def start_incognito(self, *, idempotency_key: str) -> PrivacyStatus:
        def action(database: DbSession) -> PrivacyStatus:
            state = get_state(database)
            session = IncognitoSession()
            state.incognito_json = session.model_dump_json()
            state.updated_at = utc_now()
            self._event(database, "privacy.incognito.started", {"session_id": session.id})
            return self._status_in(database, state)

        return self._mutate(idempotency_key, "incognito.start", action, PrivacyStatus)

    def stop_incognito(self, *, idempotency_key: str) -> PrivacyStatus:
        def action(database: DbSession) -> PrivacyStatus:
            state = get_state(database)
            if state.incognito_json:
                session = IncognitoSession.model_validate_json(state.incognito_json)
                state.incognito_json = session.model_copy(
                    update={"ended_at": utc_now()}
                ).model_dump_json()
            state.updated_at = utc_now()
            self._event(database, "privacy.incognito.stopped", {})
            return self._status_in(database, state)

        return self._mutate(idempotency_key, "incognito.stop", action, PrivacyStatus)

    def emergency_stop(
        self, *, idempotency_key: str, reason: str = "operator_requested"
    ) -> PrivacyStatus:
        def action(database: DbSession) -> PrivacyStatus:
            state = get_state(database)
            state.emergency_json = EmergencyStopState(
                active=True, stopped_at=utc_now(), reason=reason
            ).model_dump_json()
            state.updated_at = utc_now()
            self._event(database, "privacy.emergency_stop", {"reason": reason})
            return self._status_in(database, state)

        return self._mutate(idempotency_key, "emergency.stop", action, PrivacyStatus)

    def emergency_clear(self, *, idempotency_key: str) -> PrivacyStatus:
        def action(database: DbSession) -> PrivacyStatus:
            state = get_state(database)
            state.emergency_json = EmergencyStopState().model_dump_json()
            state.updated_at = utc_now()
            self._event(database, "privacy.emergency_clear", {})
            return self._status_in(database, state)

        return self._mutate(idempotency_key, "emergency.clear", action, PrivacyStatus)

    def update_policy(self, policy: PrivacyPolicy, *, idempotency_key: str) -> PrivacyPolicy:
        policy = PrivacyPolicy.model_validate(policy.model_dump(mode="json"))
        if (
            policy.capture_modes.get(CaptureCategory.RAW_TEXT, CaptureMode.DISABLED)
            is not CaptureMode.DISABLED
        ):
            raise ValueError("RAW_TEXT is permanently prohibited")

        def action(database: DbSession) -> PrivacyPolicy:
            state = get_state(database)
            consented = bool(state.consent_json)
            if policy.observation_enabled and not consented:
                raise PermissionError("Explicit consent is required before enabling observation")
            state.policy_json = policy.model_copy(
                update={"observation_enabled": policy.observation_enabled and consented}
            ).model_dump_json()
            state.updated_at = utc_now()
            self._purge_expired(database)
            self._event(
                database,
                "privacy.policy.updated",
                {"retention_days": policy.retention.retention_days},
            )
            return PrivacyPolicy.model_validate_json(state.policy_json)

        return self._mutate(idempotency_key, "policy.update", action, PrivacyPolicy)

    def add_exclusion(self, rule: PrivacyRule, *, idempotency_key: str) -> PrivacyRule:
        def action(database: DbSession) -> PrivacyRule:
            database.add(
                PrivacyRuleRow(
                    rule_id=rule.rule_id,
                    rule_type=rule.rule_type.value,
                    pattern=rule.pattern,
                    enabled=rule.enabled,
                    created_at=rule.created_at,
                )
            )
            self._event(
                database,
                "privacy.exclusion.added",
                {"rule_id": rule.rule_id, "rule_type": rule.rule_type.value},
            )
            return rule

        return self._mutate(idempotency_key, "exclusion.add", action, PrivacyRule)

    def remove_exclusion(self, rule_id: str, *, idempotency_key: str) -> bool:
        def action(database: DbSession) -> bool:
            deleted = database.execute(
                delete(PrivacyRuleRow).where(PrivacyRuleRow.rule_id == rule_id)
            ).rowcount  # type: ignore[attr-defined]
            if not deleted:
                raise KeyError(rule_id)
            self._event(database, "privacy.exclusion.removed", {"rule_id": rule_id})
            return True

        return self._mutate(idempotency_key, "exclusion.remove", action, bool)

    def exclusions(self) -> list[PrivacyRule]:
        with DbSession(self.engine) as database:
            return [
                PrivacyRule(
                    rule_id=row.rule_id,
                    rule_type=PrivacyRuleType(row.rule_type),
                    pattern=row.pattern,
                    enabled=row.enabled,
                    created_at=row.created_at,
                )
                for row in list_rules(database)
            ]

    def capture(self, request: CaptureRequest, *, idempotency_key: str) -> CaptureResult:
        cached = self._cached(idempotency_key, "capture")
        if cached is not None:
            return CaptureResult.model_validate(cached)
        with DbSession(self.engine) as database, database.begin():
            decision = self._decide(database, request)
            audit = PrivacyAuditEvent(
                event_category=request.category,
                decision=decision.decision,
                rule_id=decision.rule_id,
                reason=decision.reason,
                timestamp=decision.timestamp,
                adapter=request.context.adapter,
            )
            record: CapturedRecord | None = None
            if decision.decision is PrivacyDecisionType.ALLOWED:
                payload = self._minimize(request.category, request.payload)
                record = CapturedRecord(
                    category=request.category,
                    payload=payload,
                    adapter=request.context.adapter,
                )
                database.add(
                    PrivacyHistoryRow(
                        id=record.id,
                        event_category=record.category.value,
                        payload_json=json.dumps(record.payload),
                        decision=decision.decision.value,
                        rule_id=decision.rule_id,
                        reason=decision.reason,
                        timestamp=record.created_at,
                        adapter=record.adapter,
                    )
                )
            database.add(
                PrivacyHistoryRow(
                    id=f"audit-{new_id()}",
                    event_category=audit.event_category.value,
                    payload_json=None,
                    decision=audit.decision.value,
                    rule_id=audit.rule_id,
                    reason=audit.reason,
                    timestamp=audit.timestamp,
                    adapter=audit.adapter,
                )
            )
            result = CaptureResult(
                accepted=record is not None,
                decision=decision,
                audit=audit,
                record=record,
            )
            self._event(database, "privacy.capture.decided", audit.model_dump(mode="json"))
            database.add(
                PrivacyIdempotencyRow(
                    key=idempotency_key,
                    operation="capture",
                    result_json=result.model_dump_json(),
                    created_at=utc_now(),
                )
            )
            return result

    def history(self) -> list[CapturedRecord]:
        self._purge_expired()
        with DbSession(self.engine) as database:
            rows = database.scalars(
                select(PrivacyHistoryRow)
                .where(
                    PrivacyHistoryRow.payload_json.is_not(None),
                    PrivacyHistoryRow.decision == PrivacyDecisionType.ALLOWED.value,
                )
                .order_by(PrivacyHistoryRow.timestamp)
            )
            return [
                CapturedRecord(
                    id=row.id,
                    category=CaptureCategory(row.event_category),
                    payload=json.loads(row.payload_json or "{}"),
                    created_at=row.timestamp,
                    adapter=row.adapter,
                )
                for row in rows
            ]

    def audit_history(self) -> list[PrivacyAuditEvent]:
        self._purge_expired()
        with DbSession(self.engine) as database:
            rows = database.scalars(select(PrivacyHistoryRow).order_by(PrivacyHistoryRow.timestamp))
            return [
                PrivacyAuditEvent(
                    event_category=CaptureCategory(row.event_category),
                    decision=PrivacyDecisionType(row.decision),
                    rule_id=row.rule_id,
                    reason=row.reason,
                    timestamp=row.timestamp,
                    adapter=row.adapter,
                )
                for row in rows
            ]

    def export_history(self, *, before: datetime | None = None) -> str:
        records = self.history()
        if before is not None:
            records = [record for record in records if record.created_at <= before]
        return json.dumps([record.model_dump(mode="json") for record in records])

    def delete_history(self, *, idempotency_key: str, before: datetime | None = None) -> int:
        def action(database: DbSession) -> int:
            statement = delete(PrivacyHistoryRow).where(PrivacyHistoryRow.payload_json.is_not(None))
            if before is not None:
                statement = statement.where(PrivacyHistoryRow.timestamp <= before)
            count = int(database.execute(statement).rowcount or 0)  # type: ignore[attr-defined]
            self._event(database, "privacy.history.deleted", {"count": count})
            return count

        return self._mutate(idempotency_key, "history.delete", action, int)

    def events(self, after_sequence: int = 0) -> list[dict[str, Any]]:
        with DbSession(self.engine) as database:
            rows = database.scalars(
                select(PrivacyEventRow)
                .where(PrivacyEventRow.sequence > after_sequence)
                .order_by(PrivacyEventRow.sequence)
            )
            return [
                {
                    "sequence": row.sequence,
                    "event_type": row.event_type,
                    "payload": json.loads(row.payload_json),
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]

    def _decide(self, database: DbSession, request: CaptureRequest) -> PrivacyDecision:
        status = self._status_in(database, get_state(database))
        reason = "allowed"
        rule_id: str | None = None
        if status.emergency_stop_active:
            reason = "emergency_stop_active"
        elif not status.consent_granted or not status.observation_enabled:
            reason = "observation_disabled"
        elif status.paused:
            reason = "observation_paused"
        elif status.incognito_active:
            reason = "incognito_active"
        elif request.context.secure_control is not SensitiveControlClassification.NONE:
            reason = "secure_control"
        elif request.category is CaptureCategory.RAW_TEXT:
            reason = "raw_text_prohibited"
        elif (
            status.capture_modes.get(request.category, CaptureMode.DISABLED) is CaptureMode.DISABLED
        ):
            reason = "capture_category_disabled"
        else:
            matched = self._matching_rule(database, request)
            if matched is not None:
                rule_id, reason = matched.rule_id, f"excluded_{matched.rule_type.value}"
        return PrivacyDecision(
            event_category=request.category,
            decision=PrivacyDecisionType.ALLOWED
            if reason == "allowed"
            else PrivacyDecisionType.REJECTED,
            rule_id=rule_id,
            reason=reason,
            adapter=request.context.adapter,
        )

    def _matching_rule(self, database: DbSession, request: CaptureRequest) -> PrivacyRule | None:
        values = {
            PrivacyRuleType.APPLICATION: request.context.application,
            PrivacyRuleType.EXECUTABLE_PATH: request.context.executable_path,
            PrivacyRuleType.APPLICATION_CATEGORY: request.context.application_category,
            PrivacyRuleType.FOLDER: request.context.folder_path,
            PrivacyRuleType.FILE_EXTENSION: request.context.file_extension,
            PrivacyRuleType.WINDOW_TITLE: request.context.window_title,
            PrivacyRuleType.BROWSER_DOMAIN: request.context.browser_domain,
        }
        for row in list_rules(database):
            value = values.get(PrivacyRuleType(row.rule_type))
            if (
                row.enabled
                and value
                and self._matches(PrivacyRuleType(row.rule_type), value, row.pattern)
            ):
                return PrivacyRule(
                    rule_id=row.rule_id,
                    rule_type=PrivacyRuleType(row.rule_type),
                    pattern=row.pattern,
                    enabled=row.enabled,
                    created_at=row.created_at,
                )
        return None

    @staticmethod
    def _matches(rule_type: PrivacyRuleType, value: str, pattern: str) -> bool:
        if rule_type is PrivacyRuleType.FOLDER or rule_type is PrivacyRuleType.EXECUTABLE_PATH:
            normalized_value = value.replace("\\", "/").rstrip("/").casefold()
            normalized_pattern = pattern.replace("\\", "/").rstrip("/").casefold()
            return normalized_value == normalized_pattern or normalized_value.startswith(
                normalized_pattern + "/"
            )
        if rule_type is PrivacyRuleType.WINDOW_TITLE:
            return fnmatch.fnmatch(value.casefold(), pattern.casefold())
        return value.casefold() == pattern.casefold() or fnmatch.fnmatch(
            value.casefold(), pattern.casefold()
        )

    @staticmethod
    def _minimize(category: CaptureCategory, payload: dict[str, Any]) -> dict[str, Any]:
        if category is CaptureCategory.TEXT_ENTRY_METADATA:
            value = payload.get("length", payload.get("text_length", 0))
            length = int(value) if isinstance(value, (int, float)) else len(str(value))
            bucket = (
                "0" if length == 0 else "1-9" if length < 10 else "10-24" if length < 25 else "25+"
            )
            return {
                key: payload[key]
                for key in ("field_classification", "correction_count", "paste", "completed")
                if key in payload
            } | {"text_entry_occurred": True, "length_bucket": bucket}
        if category is CaptureCategory.TEMPORARY_VISION:
            allowed = {
                "application",
                "visual_state",
                "controls",
                "error_visible",
                "loading_visible",
            }
            return {key: payload[key] for key in allowed if key in payload} | {
                "raw_frame_retained": False
            }
        return {
            key: value
            for key, value in payload.items()
            if key not in {"raw_text", "text", "raw_frame"}
        }

    def _purge_expired(self, database: DbSession | None = None) -> int:
        if database is None:
            with DbSession(self.engine) as owned, owned.begin():
                return self._purge_expired(owned)
        policy = PrivacyPolicy.model_validate_json(get_state(database).policy_json)
        cutoff = utc_now() - timedelta(days=policy.retention.retention_days)
        return (
            database.execute(
                delete(PrivacyHistoryRow).where(
                    PrivacyHistoryRow.payload_json.is_not(None),
                    PrivacyHistoryRow.timestamp <= cutoff,
                )
            ).rowcount  # type: ignore[attr-defined]
            or 0
        )

    def _status_in(self, database: DbSession, state: PrivacyStateRow) -> PrivacyStatus:
        policy = PrivacyPolicy.model_validate_json(state.policy_json)
        consent = (
            ConsentRecord.model_validate_json(state.consent_json) if state.consent_json else None
        )
        emergency = EmergencyStopState.model_validate_json(state.emergency_json)
        incognito = (
            IncognitoSession.model_validate_json(state.incognito_json)
            if state.incognito_json
            else None
        )
        count = len(
            list(database.scalars(select(PrivacyRuleRow).where(PrivacyRuleRow.enabled.is_(True))))
        )
        return PrivacyStatus(
            observation_enabled=policy.observation_enabled,
            paused=policy.paused,
            consent_granted=consent is not None and consent.revoked_at is None,
            incognito_active=incognito is not None and incognito.ended_at is None,
            emergency_stop_active=emergency.active,
            capture_modes=policy.capture_modes,
            retention=policy.retention,
            exclusion_count=count,
        )

    def _event(self, database: DbSession, event_type: str, payload: dict[str, Any]) -> None:
        database.add(
            PrivacyEventRow(
                event_type=event_type,
                payload_json=json.dumps(payload),
                created_at=utc_now(),
            )
        )

    def _cached(self, key: str, operation: str) -> dict[str, Any] | None:
        with DbSession(self.engine) as database:
            row = database.get(PrivacyIdempotencyRow, key)
            if row is None:
                return None
            if row.operation != operation:
                raise ValueError("Idempotency key was already used for a different operation")
            return cast(dict[str, Any], json.loads(row.result_json))

    def _mutate(self, key: str, operation: str, action: Callable[[DbSession], T], model: Any) -> T:
        cached = self._cached(key, operation)
        if cached is not None:
            return (
                cast(T, model.model_validate(cached))
                if hasattr(model, "model_validate")
                else cast(T, model(cached))
            )
        with DbSession(self.engine) as database, database.begin():
            result = action(database)
            payload = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
            database.add(
                PrivacyIdempotencyRow(
                    key=key,
                    operation=operation,
                    result_json=json.dumps(payload),
                    created_at=utc_now(),
                )
            )
            return result
