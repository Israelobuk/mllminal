"""Mine repeated semantic event sequences without raw content or replay."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from mllminal.interaction.contracts import InteractionEvent
from mllminal.mining.contracts import (
    MinedStep,
    MiningRequest,
    MiningResult,
    WorkflowCandidate,
)

type _Signature = tuple[tuple[str | None, ...], ...]
_MAX_SESSION_GAP = timedelta(minutes=5)


class WorkflowMiningService:
    def mine(self, events: list[InteractionEvent], request: MiningRequest) -> MiningResult:
        now = datetime.now(UTC)
        cutoff = now - timedelta(minutes=request.lookback_minutes)
        recent = sorted(
            (event for event in events if event.created_at >= cutoff), key=lambda e: e.created_at
        )
        sessions = self._sessions(recent)
        matches: dict[_Signature, list[tuple[list[InteractionEvent], str]]] = defaultdict(list)
        for session in sessions:
            seen: set[_Signature] = set()
            limit = min(request.max_steps, len(session))
            for size in range(2, limit + 1):
                for start in range(len(session) - size + 1):
                    window = session[start : start + size]
                    signature = tuple(self._step_key(event) for event in window)
                    if signature not in seen:
                        matches[signature].append((window, session[0].id))
                        seen.add(signature)
        candidates: list[WorkflowCandidate] = []
        for _signature, occurrences in matches.items():
            if len(occurrences) < request.minimum_occurrences:
                continue
            first_window = occurrences[0][0]
            steps = [self._step(event) for event in first_window]
            candidates.append(
                WorkflowCandidate(
                    application=steps[0].application,
                    steps=steps,
                    occurrences=len(occurrences),
                    confidence=min(1.0, len(occurrences) / max(1, len(sessions))),
                    first_seen=min(window[0].created_at for window, _ in occurrences),
                    last_seen=max(window[-1].created_at for window, _ in occurrences),
                    source_event_ids=[event.id for event in first_window],
                )
            )
        candidates.sort(key=lambda candidate: (-candidate.occurrences, -len(candidate.steps)))
        return MiningResult(
            event_count=len(recent),
            session_count=len(sessions),
            candidates=candidates,
        )

    @staticmethod
    def _sessions(events: list[InteractionEvent]) -> list[list[InteractionEvent]]:
        sessions: list[list[InteractionEvent]] = []
        for event in events:
            application = event.target.application if event.target else "unknown"
            if (
                not sessions
                or event.created_at - sessions[-1][-1].created_at > _MAX_SESSION_GAP
                or (sessions[-1][-1].target and sessions[-1][-1].target.application != application)
            ):
                sessions.append([event])
            else:
                sessions[-1].append(event)
        return sessions

    @staticmethod
    def _step(event: InteractionEvent) -> MinedStep:
        target = event.target
        text = event.text_metadata
        return MinedStep(
            application=target.application if target else "unknown",
            kind=event.kind.value,
            control_role=target.control_role if target else None,
            control_name=target.control_name if target else None,
            action_type=target.action_type if target else None,
            shortcut=event.shortcut,
            navigation_key=event.navigation_key.value if event.navigation_key else None,
            text_field_classification=text.field_classification if text else None,
            text_length_bucket=text.length_bucket if text else None,
        )

    @classmethod
    def _step_key(cls, event: InteractionEvent) -> tuple[str | None, ...]:
        step = cls._step(event)
        return (
            step.application,
            step.kind,
            step.control_role,
            step.control_name,
            step.action_type,
            step.shortcut,
            step.navigation_key,
            step.text_field_classification,
            step.text_length_bucket,
        )
