"""Deterministic activity projection over privacy-filtered local events."""

import json
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any, cast

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as DbSession

from mllminal.activity.contracts import (
    ActivityRefreshResult,
    ActivitySegment,
    ActivitySource,
    ActivitySummary,
    ApplicationSession,
    BoundaryKind,
    ContextSwitch,
    TaskBoundary,
    TaskSession,
)
from mllminal.activity.persistence import (
    ActivityIdempotencyRow,
    ActivitySegmentRow,
    ActivitySummaryRow,
    ApplicationSessionRow,
    ContextSwitchRow,
    TaskBoundaryRow,
    TaskSessionRow,
)
from mllminal.contracts import utc_now
from mllminal.device.observer import DeviceObserver
from mllminal.interaction.service import InteractionService
from mllminal.persistence import Base


class ActivityService:
    def __init__(
        self,
        database_path: Path,
        interaction: InteractionService,
        observer: DeviceObserver,
        *,
        idle_timeout_seconds: int = 300,
    ) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.interaction = interaction
        self.observer = observer
        self.idle_timeout = timedelta(seconds=idle_timeout_seconds)
        self.engine = create_engine(f"sqlite:///{database_path}")
        Base.metadata.create_all(self.engine)

    def refresh(
        self, *, lookback_minutes: int = 1440, idempotency_key: str
    ) -> ActivityRefreshResult:
        cached = self._cached(idempotency_key, "activity.refresh")
        if cached is not None:
            return ActivityRefreshResult.model_validate(cached)
        period_end = utc_now()
        period_start = period_end - timedelta(minutes=lookback_minutes)
        segments = self._build_segments(period_start)
        application_sessions = self._build_application_sessions(segments)
        task_sessions = self._build_task_sessions(application_sessions)
        switches = self._build_switches(segments)
        boundaries = self._build_boundaries(task_sessions, switches)
        summary = ActivitySummary(
            period_started_at=period_start,
            period_ended_at=period_end,
            segment_count=len(segments),
            application_session_count=len(application_sessions),
            task_session_count=len(task_sessions),
            context_switch_count=len(switches),
            task_boundary_count=len(boundaries),
            applications=sorted({segment.application for segment in segments}),
        )
        result = ActivityRefreshResult(
            summary=summary,
            segments=segments,
            application_sessions=application_sessions,
            task_sessions=task_sessions,
            context_switches=switches,
            task_boundaries=boundaries,
        )
        self._persist(result)
        self._save_idempotency(idempotency_key, "activity.refresh", result)
        return result

    def summary(self) -> ActivitySummary | None:
        with DbSession(self.engine) as database:
            row = database.scalar(
                select(ActivitySummaryRow).order_by(ActivitySummaryRow.created_at.desc())
            )
            return ActivitySummary.model_validate_json(row.payload_json) if row else None

    def segments(self) -> list[ActivitySegment]:
        return self._load(ActivitySegmentRow, ActivitySegment)

    def application_sessions(self) -> list[ApplicationSession]:
        return self._load(ApplicationSessionRow, ApplicationSession)

    def task_sessions(self) -> list[TaskSession]:
        return self._load(TaskSessionRow, TaskSession)

    def context_switches(self) -> list[ContextSwitch]:
        return self._load(ContextSwitchRow, ContextSwitch)

    def task_boundaries(self) -> list[TaskBoundary]:
        return self._load(TaskBoundaryRow, TaskBoundary)

    def _build_segments(self, period_start: datetime) -> list[ActivitySegment]:
        signals: list[tuple[datetime, ActivitySource, str, str | None, str, str]] = []
        for event in self.interaction.events():
            timestamp = self._as_utc(event.created_at)
            if timestamp < period_start:
                continue
            application = event.target.application if event.target else "unknown"
            window = event.target.window if event.target else None
            signals.append(
                (
                    timestamp,
                    ActivitySource.INTERACTION,
                    application,
                    window,
                    event.id,
                    event.kind.value,
                )
            )
        for event in self.observer.events():
            timestamp = self._as_utc(event.timestamp)
            if timestamp < period_start:
                continue
            application = event.application.process_name if event.application else "unknown"
            signals.append(
                (
                    timestamp,
                    ActivitySource.DEVICE,
                    application,
                    event.window.title_classification if event.window else None,
                    event.event_id,
                    event.event_type,
                )
            )
        signals.sort(key=lambda item: item[0])
        segments: list[ActivitySegment] = []
        current: ActivitySegment | None = None
        for timestamp, source, application, window, event_id, event_type in signals:
            if (
                current is None
                or current.application != application
                or current.source is not source
                or timestamp - current.ended_at > self.idle_timeout
            ):
                if current is not None:
                    segments.append(current)
                current = ActivitySegment(
                    source=source,
                    application=application,
                    window=window,
                    started_at=timestamp,
                    ended_at=timestamp,
                    event_ids=[event_id],
                    event_types=[event_type],
                )
            else:
                current.ended_at = timestamp
                current.event_ids.append(event_id)
                current.event_types.append(event_type)
            current.duration_seconds = max(
                0.0, (current.ended_at - current.started_at).total_seconds()
            )
        if current is not None:
            segments.append(current)
        return segments

    @staticmethod
    def _build_application_sessions(
        segments: list[ActivitySegment],
    ) -> list[ApplicationSession]:
        return [
            ApplicationSession(
                application=segment.application,
                started_at=segment.started_at,
                ended_at=segment.ended_at,
                segment_ids=[segment.id],
                event_count=len(segment.event_ids),
            )
            for segment in segments
        ]

    @staticmethod
    def _build_task_sessions(
        application_sessions: list[ApplicationSession],
    ) -> list[TaskSession]:
        return [
            TaskSession(
                title=f"Activity in {session.application}",
                started_at=session.started_at,
                ended_at=session.ended_at,
                application_session_ids=[session.id],
                segment_ids=session.segment_ids,
            )
            for session in application_sessions
        ]

    @staticmethod
    def _build_switches(segments: list[ActivitySegment]) -> list[ContextSwitch]:
        return [
            ContextSwitch(
                from_application=previous.application,
                to_application=current.application,
                occurred_at=current.started_at,
            )
            for previous, current in pairwise(segments)
            if previous.application != current.application
        ]

    @staticmethod
    def _build_boundaries(
        tasks: list[TaskSession], switches: list[ContextSwitch]
    ) -> list[TaskBoundary]:
        boundaries: list[TaskBoundary] = []
        for task in tasks:
            boundaries.append(
                TaskBoundary(
                    kind=BoundaryKind.TASK_STARTED,
                    occurred_at=task.started_at,
                    application=task.title.removeprefix("Activity in "),
                    task_session_id=task.id,
                    reason="first activity in session",
                )
            )
            boundaries.append(
                TaskBoundary(
                    kind=BoundaryKind.TASK_ENDED,
                    occurred_at=task.ended_at,
                    application=task.title.removeprefix("Activity in "),
                    task_session_id=task.id,
                    reason="last observed activity in session",
                )
            )
        boundaries.extend(
            TaskBoundary(
                kind=BoundaryKind.CONTEXT_SWITCH,
                occurred_at=switch.occurred_at,
                application=switch.to_application,
                reason=switch.reason,
            )
            for switch in switches
        )
        return sorted(boundaries, key=lambda boundary: boundary.occurred_at)

    def _persist(self, result: ActivityRefreshResult) -> None:
        with DbSession(self.engine) as database, database.begin():
            for row_type in (
                ActivitySegmentRow,
                ApplicationSessionRow,
                TaskSessionRow,
                ContextSwitchRow,
                TaskBoundaryRow,
                ActivitySummaryRow,
            ):
                database.execute(delete(row_type))
            now = utc_now()
            for value, row_type in (
                (result.segments, ActivitySegmentRow),
                (result.application_sessions, ApplicationSessionRow),
                (result.task_sessions, TaskSessionRow),
                (result.context_switches, ContextSwitchRow),
                (result.task_boundaries, TaskBoundaryRow),
            ):
                database.add_all(
                    row_type(
                        id=item.id,
                        payload_json=item.model_dump_json(),
                        created_at=now,
                    )
                    for item in value
                )
            database.add(
                ActivitySummaryRow(
                    id=result.summary.id,
                    payload_json=result.summary.model_dump_json(),
                    created_at=now,
                )
            )

    def _load(self, row_type: Any, model: Any) -> list[Any]:
        with DbSession(self.engine) as database:
            rows = database.scalars(select(row_type).order_by(row_type.created_at))
            return [model.model_validate_json(row.payload_json) for row in rows]

    def _cached(self, key: str, operation: str) -> dict[str, Any] | None:
        with DbSession(self.engine) as database:
            row = database.get(ActivityIdempotencyRow, key)
            if row is None:
                return None
            if row.operation != operation:
                raise ValueError("Idempotency key was already used for a different operation")
            return cast(dict[str, Any], json.loads(row.result_json))

    def _save_idempotency(self, key: str, operation: str, result: Any) -> None:
        with DbSession(self.engine) as database, database.begin():
            database.add(
                ActivityIdempotencyRow(
                    key=key,
                    operation=operation,
                    result_json=result.model_dump_json(),
                    created_at=utc_now(),
                )
            )

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value
