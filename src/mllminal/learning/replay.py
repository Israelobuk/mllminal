"""Durable, privacy-preserving learning state and experience replay."""

import json
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    delete,
    func,
    select,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import Session as DbSession

from mllminal.learning.contracts import (
    ACTION_SPACE_VERSION,
    FEATURE_VERSION,
    EvaluationReport,
    ExperienceRecord,
    LearningStatus,
    PolicyAction,
    PolicyDecision,
    PolicyLifecycle,
    PolicyVersion,
    PromotionDecision,
    PromotionOutcome,
    ReplaySample,
    RollbackRecord,
    TrainingRun,
    utc_now,
)
from mllminal.persistence import Base, Store


class LearningSettingsRow(Base):
    __tablename__ = "learning_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    enabled: Mapped[bool]
    automatic_promotion_enabled: Mapped[bool]
    minimum_experience_count: Mapped[int]
    replay_capacity: Mapped[int]
    seed: Mapped[int]
    confidence_threshold: Mapped[float]
    updated_at: Mapped[datetime]


class PolicyDecisionRow(Base):
    __tablename__ = "policy_decisions"
    __table_args__ = (UniqueConstraint("task_id", "decision_sequence"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(String, index=True)
    decision_sequence: Mapped[int]
    payload_json: Mapped[str] = mapped_column(Text)
    finalization_key: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime]


class ExperienceRow(Base):
    __tablename__ = "experiences"
    __table_args__ = (
        UniqueConstraint("task_id", "decision_sequence"),
        UniqueConstraint("idempotency_key"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(String, index=True)
    decision_id: Mapped[str] = mapped_column(ForeignKey("policy_decisions.id"), index=True)
    decision_sequence: Mapped[int]
    idempotency_key: Mapped[str]
    status: Mapped[str]
    reward: Mapped[float | None]
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]


class ReplayEntryRow(Base):
    __tablename__ = "replay_entries"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    experience_id: Mapped[str] = mapped_column(ForeignKey("experiences.id"), unique=True)
    features_json: Mapped[str] = mapped_column(Text)
    action: Mapped[str]
    reward: Mapped[float]
    sampling_weight: Mapped[float]
    created_at: Mapped[datetime]
    consumed_at: Mapped[datetime | None] = mapped_column(nullable=True)


class LearningEventRow(Base):
    __tablename__ = "learning_events"
    sequence: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_type: Mapped[str]
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]


class TrainingRunRow(Base):
    __tablename__ = "training_runs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str]
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]


class EvaluationReportRow(Base):
    __tablename__ = "evaluation_reports"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    training_run_id: Mapped[str] = mapped_column(ForeignKey("training_runs.id"), index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]


class PolicyVersionRow(Base):
    __tablename__ = "policy_versions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[int] = mapped_column(unique=True)
    lifecycle: Mapped[str]
    promoted: Mapped[bool] = mapped_column(Boolean, default=False)
    checkpoint_sha256: Mapped[str | None] = mapped_column(String, nullable=True)
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]


Index(
    "uq_policy_versions_one_promoted",
    PolicyVersionRow.promoted,
    unique=True,
    sqlite_where=PolicyVersionRow.promoted.is_(True),
)


class PromotionRecordRow(Base):
    __tablename__ = "promotion_records"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    policy_version_id: Mapped[str] = mapped_column(ForeignKey("policy_versions.id"), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]


class RollbackRecordRow(Base):
    __tablename__ = "rollback_records"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    from_policy_version_id: Mapped[str] = mapped_column(ForeignKey("policy_versions.id"))
    to_policy_version_id: Mapped[str] = mapped_column(ForeignKey("policy_versions.id"))
    idempotency_key: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    payload_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]


@dataclass(frozen=True)
class LearningEvent:
    sequence: int
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class ReplayEntry:
    experience_id: str
    features: tuple[float, ...]
    action: PolicyAction
    reward: float
    sampling_weight: float
    created_at: datetime
    consumed_at: datetime | None


_FORBIDDEN_KEYS = {
    "message",
    "messages",
    "tool_argument",
    "tool_arguments",
    "tool_output",
    "file_content",
    "file_contents",
    "auth_error",
    "secret",
    "secrets",
}


def _ensure_safe_payload(payload: dict[str, Any]) -> None:
    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                if key.lower() in _FORBIDDEN_KEYS:
                    raise ValueError(f"learning payload contains forbidden field: {key}")
                visit(nested)
        elif isinstance(value, list | tuple):
            for nested in value:
                visit(nested)

    visit(payload)


def _utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _required_utc(value: datetime) -> datetime:
    converted = _utc(value)
    assert converted is not None
    return converted


class LearningRepository(Store):
    """Transactional repository isolated from runtime/provider record types."""

    def __init__(self, database_path: Path) -> None:
        super().__init__(database_path)

    def initialize(self) -> None:
        super().initialize()
        self._bootstrap()

    def _bootstrap(self) -> None:
        with self.transaction() as database:
            if database.get(LearningSettingsRow, 1) is None:
                now = utc_now()
                database.add(
                    LearningSettingsRow(
                        id=1,
                        enabled=True,
                        automatic_promotion_enabled=False,
                        minimum_experience_count=100,
                        replay_capacity=10_000,
                        seed=42,
                        confidence_threshold=0.65,
                        updated_at=now,
                    )
                )
            if database.scalar(select(func.count()).select_from(PolicyVersionRow)) == 0:
                fallback = PolicyVersion(
                    version=0,
                    name="policy_v0",
                    lifecycle=PolicyLifecycle.ACTIVE,
                    feature_version=FEATURE_VERSION,
                    action_space_version=ACTION_SPACE_VERSION,
                    checkpoint_sha256=None,
                    training_run_id=None,
                )
                database.add(
                    PolicyVersionRow(
                        id=fallback.id,
                        version=0,
                        lifecycle=fallback.lifecycle.value,
                        promoted=True,
                        checkpoint_sha256=None,
                        payload_json=fallback.model_dump_json(),
                        created_at=fallback.created_at,
                    )
                )

    def get_settings(self) -> LearningStatus:
        with DbSession(self.engine) as database:
            row = database.get(LearningSettingsRow, 1)
            if row is None:
                raise KeyError("learning_settings")
            promoted = database.scalar(
                select(PolicyVersionRow).where(PolicyVersionRow.promoted.is_(True))
            )
            return LearningStatus(
                enabled=row.enabled,
                automatic_promotion_enabled=row.automatic_promotion_enabled,
                active_policy_version_id=promoted.id if promoted else None,
                eligible_experience_count=self.count_experiences(status="ELIGIBLE"),
                minimum_experience_count=row.minimum_experience_count,
                replay_capacity=row.replay_capacity,
                seed=row.seed,
                confidence_threshold=row.confidence_threshold,
                updated_at=_required_utc(row.updated_at),
            )

    def update_settings(self, **changes: Any) -> LearningStatus:
        allowed = {
            "enabled",
            "automatic_promotion_enabled",
            "minimum_experience_count",
            "replay_capacity",
            "seed",
            "confidence_threshold",
        }
        if not set(changes) <= allowed:
            raise ValueError("unknown learning setting")
        with self.transaction() as database:
            row = database.get(LearningSettingsRow, 1)
            if row is None:
                raise KeyError("learning_settings")
            for name, value in changes.items():
                setattr(row, name, value)
            row.updated_at = utc_now()
        return self.get_settings()

    def save_decision(
        self, decision: PolicyDecision, *, decision_sequence: int
    ) -> tuple[PolicyDecision, bool]:
        payload = decision.model_dump(mode="json")
        _ensure_safe_payload(payload)
        with self.transaction() as database:
            existing = database.get(PolicyDecisionRow, decision.id)
            if existing is not None:
                return PolicyDecision.model_validate_json(existing.payload_json), False
            database.add(
                PolicyDecisionRow(
                    id=decision.id,
                    task_id=decision.task_id,
                    decision_sequence=decision_sequence,
                    payload_json=decision.model_dump_json(),
                    finalization_key=None,
                    finalized_at=None,
                    created_at=decision.created_at,
                )
            )
            self._append_learning_event(
                database, "learning.decision.created", {"decision_id": decision.id}
            )
        return decision, True

    def finalize_decision(
        self, decision_id: str, *, idempotency_key: str
    ) -> tuple[PolicyDecision, bool]:
        with self.transaction() as database:
            row = database.get(PolicyDecisionRow, decision_id)
            if row is None:
                raise KeyError(decision_id)
            if row.finalization_key is not None:
                if row.finalization_key != idempotency_key:
                    raise ValueError("decision already finalized with another key")
                return PolicyDecision.model_validate_json(row.payload_json), False
            row.finalization_key = idempotency_key
            row.finalized_at = utc_now()
            self._append_learning_event(
                database, "learning.decision.finalized", {"decision_id": decision_id}
            )
            return PolicyDecision.model_validate_json(row.payload_json), True

    def list_decisions(self, task_id: str | None = None) -> list[PolicyDecision]:
        with DbSession(self.engine) as database:
            statement = select(PolicyDecisionRow).order_by(PolicyDecisionRow.created_at)
            if task_id is not None:
                statement = statement.where(PolicyDecisionRow.task_id == task_id)
            return [
                PolicyDecision.model_validate_json(row.payload_json)
                for row in database.scalars(statement)
            ]

    def count_decisions(self) -> int:
        with DbSession(self.engine) as database:
            return int(database.scalar(select(func.count()).select_from(PolicyDecisionRow)) or 0)

    def save_experience(
        self, experience: ExperienceRecord, *, decision_sequence: int
    ) -> tuple[ExperienceRecord, bool]:
        payload = experience.model_dump(mode="json")
        _ensure_safe_payload(payload)
        with self.transaction() as database:
            existing = database.scalar(
                select(ExperienceRow).where(
                    (ExperienceRow.id == experience.id)
                    | (ExperienceRow.idempotency_key == experience.idempotency_key)
                )
            )
            if existing is not None:
                return ExperienceRecord.model_validate_json(existing.payload_json), False
            database.add(
                ExperienceRow(
                    id=experience.id,
                    task_id=experience.task_id,
                    decision_id=experience.decision_id,
                    decision_sequence=decision_sequence,
                    idempotency_key=experience.idempotency_key,
                    status=experience.status.value,
                    reward=experience.reward.total if experience.reward else None,
                    payload_json=experience.model_dump_json(),
                    created_at=experience.created_at,
                )
            )
            self._append_learning_event(
                database, "learning.experience.created", {"experience_id": experience.id}
            )
        return experience, True

    def get_experience(self, experience_id: str) -> ExperienceRecord:
        with DbSession(self.engine) as database:
            row = database.get(ExperienceRow, experience_id)
            if row is None:
                raise KeyError(experience_id)
            return ExperienceRecord.model_validate_json(row.payload_json)

    def list_experiences(self, status: str | None = None) -> list[ExperienceRecord]:
        with DbSession(self.engine) as database:
            statement = select(ExperienceRow).order_by(ExperienceRow.created_at)
            if status is not None:
                statement = statement.where(ExperienceRow.status == status)
            return [
                ExperienceRecord.model_validate_json(row.payload_json)
                for row in database.scalars(statement)
            ]

    def count_experiences(self, status: str | None = None) -> int:
        with DbSession(self.engine) as database:
            statement = select(func.count()).select_from(ExperienceRow)
            if status is not None:
                statement = statement.where(ExperienceRow.status == status)
            return int(database.scalar(statement) or 0)

    @staticmethod
    def _weight(reward: float) -> float:
        return min(4.0, max(0.25, abs(reward)))

    def add_replay_entry(
        self,
        experience_id: str,
        *,
        features: tuple[float, ...],
        action: PolicyAction,
        reward: float,
    ) -> tuple[ReplayEntry, bool]:
        if len(features) != 15:
            raise ValueError("replay features must contain 15 values")
        with self.transaction() as database:
            existing = database.scalar(
                select(ReplayEntryRow).where(ReplayEntryRow.experience_id == experience_id)
            )
            if existing is not None:
                return self._replay_entry(existing), False
            row = ReplayEntryRow(
                experience_id=experience_id,
                features_json=json.dumps(features),
                action=action.value,
                reward=reward,
                sampling_weight=self._weight(reward),
                created_at=utc_now(),
                consumed_at=None,
            )
            database.add(row)
            database.flush()
            settings = database.get(LearningSettingsRow, 1)
            if settings is None:
                raise KeyError("learning_settings")
            count = int(database.scalar(select(func.count()).select_from(ReplayEntryRow)) or 0)
            excess = count - settings.replay_capacity
            if excess > 0:
                oldest = list(
                    database.scalars(
                        select(ReplayEntryRow.id).order_by(ReplayEntryRow.id).limit(excess)
                    )
                )
                database.execute(delete(ReplayEntryRow).where(ReplayEntryRow.id.in_(oldest)))
            result = self._replay_entry(row)
        return result, True

    def get_replay_entry(self, experience_id: str) -> ReplayEntry:
        with DbSession(self.engine) as database:
            row = database.scalar(
                select(ReplayEntryRow).where(ReplayEntryRow.experience_id == experience_id)
            )
            if row is None:
                raise KeyError(experience_id)
            return self._replay_entry(row)

    def count_replay_entries(self) -> int:
        with DbSession(self.engine) as database:
            return int(database.scalar(select(func.count()).select_from(ReplayEntryRow)) or 0)

    def replay_weight(self, experience_id: str) -> float:
        return self.get_replay_entry(experience_id).sampling_weight

    def mark_replay_consumed(self, experience_id: str) -> ReplayEntry:
        with self.transaction() as database:
            row = database.scalar(
                select(ReplayEntryRow).where(ReplayEntryRow.experience_id == experience_id)
            )
            if row is None:
                raise KeyError(experience_id)
            if row.consumed_at is None:
                row.consumed_at = utc_now()
            return self._replay_entry(row)

    def sample_replay(
        self, size: int, *, seed: int, reward_balanced: bool = False
    ) -> list[ReplaySample]:
        with DbSession(self.engine) as database:
            rows = list(database.scalars(select(ReplayEntryRow).order_by(ReplayEntryRow.id)))
        generator = random.Random(seed)
        if not reward_balanced:
            chosen = generator.sample(rows, min(size, len(rows)))
        else:
            positive = [row for row in rows if row.reward >= 0]
            negative = [row for row in rows if row.reward < 0]
            generator.shuffle(positive)
            generator.shuffle(negative)
            negative_target = size // 2
            positive_target = size - negative_target
            chosen = negative[:negative_target] + positive[:positive_target]
            remaining = [
                row
                for row in negative[negative_target:] + positive[positive_target:]
                if row not in chosen
            ]
            generator.shuffle(remaining)
            chosen.extend(remaining[: max(0, min(size, len(rows)) - len(chosen))])
        return [
            ReplaySample(
                experience_id=row.experience_id,
                features=tuple(json.loads(row.features_json)),
                action=PolicyAction(row.action),
                reward=row.reward,
            )
            for row in chosen
        ]

    def append_event(self, event_type: str, payload: dict[str, Any]) -> LearningEvent:  # type: ignore[override]
        _ensure_safe_payload(payload)
        with self.transaction() as database:
            return self._append_learning_event(database, event_type, payload)

    def _append_learning_event(
        self, database: DbSession, event_type: str, payload: dict[str, Any]
    ) -> LearningEvent:
        _ensure_safe_payload(payload)
        row = LearningEventRow(
            event_type=event_type,
            payload_json=json.dumps(payload, sort_keys=True),
            created_at=utc_now(),
        )
        database.add(row)
        database.flush()
        return self._event(row)

    def list_events(self, after_sequence: int = 0) -> list[LearningEvent]:  # type: ignore[override]
        with DbSession(self.engine) as database:
            rows = database.scalars(
                select(LearningEventRow)
                .where(LearningEventRow.sequence > after_sequence)
                .order_by(LearningEventRow.sequence)
            )
            return [self._event(row) for row in rows]

    def create_policy_version(self, *, checkpoint_sha256: str) -> PolicyVersion:
        with self.transaction() as database:
            version = int(database.scalar(select(func.max(PolicyVersionRow.version))) or 0) + 1
            policy = PolicyVersion(
                version=version,
                name=f"policy_v{version}",
                checkpoint_sha256=checkpoint_sha256,
            )
            database.add(
                PolicyVersionRow(
                    id=policy.id,
                    version=version,
                    lifecycle=policy.lifecycle.value,
                    promoted=False,
                    checkpoint_sha256=checkpoint_sha256,
                    payload_json=policy.model_dump_json(),
                    created_at=policy.created_at,
                )
            )
            self._append_learning_event(
                database, "learning.policy.created", {"policy_version_id": policy.id}
            )
            return policy

    def list_policy_versions(self) -> list[PolicyVersion]:
        with DbSession(self.engine) as database:
            return [
                PolicyVersion.model_validate_json(row.payload_json)
                for row in database.scalars(
                    select(PolicyVersionRow).order_by(PolicyVersionRow.version)
                )
            ]

    def get_promoted_policy(self) -> PolicyVersion:
        with DbSession(self.engine) as database:
            row = database.scalar(
                select(PolicyVersionRow).where(PolicyVersionRow.promoted.is_(True))
            )
            if row is None:
                raise KeyError("promoted_policy")
            return PolicyVersion.model_validate_json(row.payload_json)

    def promote_policy(
        self, policy_version_id: str, *, reason: str, idempotency_key: str
    ) -> tuple[PolicyVersion, bool]:
        with self.transaction() as database:
            existing = database.scalar(
                select(PromotionRecordRow).where(
                    PromotionRecordRow.idempotency_key == idempotency_key
                )
            )
            if existing is not None:
                row = database.get(PolicyVersionRow, existing.policy_version_id)
                if row is None:
                    raise KeyError(existing.policy_version_id)
                if row.id != policy_version_id:
                    raise ValueError("promotion key already used for another policy")
                return PolicyVersion.model_validate_json(row.payload_json), False
            row = database.get(PolicyVersionRow, policy_version_id)
            if row is None:
                raise KeyError(policy_version_id)
            current = database.scalar(
                select(PolicyVersionRow).where(PolicyVersionRow.promoted.is_(True))
            )
            if current is not None:
                current.promoted = False
                current.lifecycle = PolicyLifecycle.RETIRED.value
            row.promoted = True
            row.lifecycle = PolicyLifecycle.ACTIVE.value
            policy = PolicyVersion.model_validate_json(row.payload_json).model_copy(
                update={"lifecycle": PolicyLifecycle.ACTIVE}
            )
            row.payload_json = policy.model_dump_json()
            promotion = PromotionDecision(
                policy_version_id=row.id,
                evaluation_report_id="explicit",
                outcome=PromotionOutcome.APPROVED,
                reason=reason,
                explicitly_approved=True,
            )
            database.add(
                PromotionRecordRow(
                    id=promotion.id,
                    policy_version_id=row.id,
                    idempotency_key=idempotency_key,
                    payload_json=promotion.model_dump_json(),
                    created_at=promotion.decided_at,
                )
            )
            database.flush()
            self._append_learning_event(
                database, "learning.policy.promoted", {"policy_version_id": row.id}
            )
            return policy, True

    def save_training_run(self, run: TrainingRun) -> TrainingRun:
        self._save_contract(
            TrainingRunRow(
                id=run.id,
                status=run.status.value,
                payload_json=run.model_dump_json(),
                created_at=run.created_at,
            )
        )
        return run

    def list_training_runs(self) -> list[TrainingRun]:
        return self._list_contracts(TrainingRunRow, TrainingRun)

    def save_evaluation_report(self, report: EvaluationReport) -> EvaluationReport:
        self._save_contract(
            EvaluationReportRow(
                id=report.id,
                training_run_id=report.training_run_id,
                payload_json=report.model_dump_json(),
                created_at=report.created_at,
            )
        )
        return report

    def list_evaluation_reports(self) -> list[EvaluationReport]:
        return self._list_contracts(EvaluationReportRow, EvaluationReport)

    def save_promotion_record(self, record: PromotionDecision) -> PromotionDecision:
        self._save_contract(
            PromotionRecordRow(
                id=record.id,
                policy_version_id=record.policy_version_id,
                idempotency_key=None,
                payload_json=record.model_dump_json(),
                created_at=record.decided_at,
            )
        )
        return record

    def list_promotion_records(self) -> list[PromotionDecision]:
        return self._list_contracts(PromotionRecordRow, PromotionDecision)

    def save_rollback_record(self, record: RollbackRecord) -> RollbackRecord:
        self._save_contract(
            RollbackRecordRow(
                id=record.id,
                from_policy_version_id=record.from_policy_version_id,
                to_policy_version_id=record.to_policy_version_id,
                payload_json=record.model_dump_json(),
                created_at=record.rolled_back_at,
            )
        )
        return record

    def list_rollback_records(self) -> list[RollbackRecord]:
        return self._list_contracts(RollbackRecordRow, RollbackRecord)

    def get_training_run(self, record_id: str) -> TrainingRun:
        return cast(TrainingRun, self._get_contract(TrainingRunRow, TrainingRun, record_id))

    def count_training_runs(self) -> int:
        return self._count_rows(TrainingRunRow)

    def get_evaluation_report(self, record_id: str) -> EvaluationReport:
        return cast(
            EvaluationReport,
            self._get_contract(EvaluationReportRow, EvaluationReport, record_id),
        )

    def count_evaluation_reports(self) -> int:
        return self._count_rows(EvaluationReportRow)

    def get_policy_version(self, record_id: str) -> PolicyVersion:
        return cast(PolicyVersion, self._get_contract(PolicyVersionRow, PolicyVersion, record_id))

    def count_policy_versions(self) -> int:
        return self._count_rows(PolicyVersionRow)

    def get_promotion_record(self, record_id: str) -> PromotionDecision:
        return cast(
            PromotionDecision,
            self._get_contract(PromotionRecordRow, PromotionDecision, record_id),
        )

    def count_promotion_records(self) -> int:
        return self._count_rows(PromotionRecordRow)

    def get_rollback_record(self, record_id: str) -> RollbackRecord:
        return cast(
            RollbackRecord,
            self._get_contract(RollbackRecordRow, RollbackRecord, record_id),
        )

    def count_rollback_records(self) -> int:
        return self._count_rows(RollbackRecordRow)

    def rollback_policy(
        self, policy_version_id: str, *, reason: str, idempotency_key: str
    ) -> tuple[RollbackRecord, bool]:
        with self.transaction() as database:
            existing = database.scalar(
                select(RollbackRecordRow).where(
                    RollbackRecordRow.idempotency_key == idempotency_key
                )
            )
            if existing is not None:
                if existing.to_policy_version_id != policy_version_id:
                    raise ValueError("rollback key already used for another policy")
                return RollbackRecord.model_validate_json(existing.payload_json), False
            current = database.scalar(
                select(PolicyVersionRow).where(PolicyVersionRow.promoted.is_(True))
            )
            target = database.get(PolicyVersionRow, policy_version_id)
            if current is None or target is None:
                raise KeyError(policy_version_id)
            current.promoted = False
            current.lifecycle = PolicyLifecycle.ROLLED_BACK.value
            database.flush()
            target.promoted = True
            target.lifecycle = PolicyLifecycle.ACTIVE.value
            current_policy = PolicyVersion.model_validate_json(current.payload_json).model_copy(
                update={"lifecycle": PolicyLifecycle.ROLLED_BACK}
            )
            target_policy = PolicyVersion.model_validate_json(target.payload_json).model_copy(
                update={"lifecycle": PolicyLifecycle.ACTIVE}
            )
            current.payload_json = current_policy.model_dump_json()
            target.payload_json = target_policy.model_dump_json()
            record = RollbackRecord(
                from_policy_version_id=current.id,
                to_policy_version_id=target.id,
                reason=reason,
            )
            database.add(
                RollbackRecordRow(
                    id=record.id,
                    from_policy_version_id=current.id,
                    to_policy_version_id=target.id,
                    idempotency_key=idempotency_key,
                    payload_json=record.model_dump_json(),
                    created_at=record.rolled_back_at,
                )
            )
            self._append_learning_event(
                database, "learning.policy.rolled_back", {"policy_version_id": target.id}
            )
            return record, True

    def _get_contract(self, row_type: Any, contract_type: Any, record_id: str) -> Any:
        with DbSession(self.engine) as database:
            row = database.get(row_type, record_id)
            if row is None:
                raise KeyError(record_id)
            return contract_type.model_validate_json(row.payload_json)

    def _count_rows(self, row_type: Any) -> int:
        with DbSession(self.engine) as database:
            return int(database.scalar(select(func.count()).select_from(row_type)) or 0)

    def _save_contract(self, row: Any) -> None:
        _ensure_safe_payload(json.loads(row.payload_json))
        with self.transaction() as database:
            if database.get(type(row), row.id) is None:
                database.add(row)

    def _list_contracts(self, row_type: Any, contract_type: Any) -> list[Any]:
        with DbSession(self.engine) as database:
            rows = database.scalars(select(row_type).order_by(row_type.created_at))
            return [contract_type.model_validate_json(row.payload_json) for row in rows]

    @staticmethod
    def _replay_entry(row: ReplayEntryRow) -> ReplayEntry:
        return ReplayEntry(
            experience_id=row.experience_id,
            features=tuple(json.loads(row.features_json)),
            action=PolicyAction(row.action),
            reward=row.reward,
            sampling_weight=row.sampling_weight,
            created_at=_required_utc(row.created_at),
            consumed_at=_utc(row.consumed_at),
        )

    @staticmethod
    def _event(row: LearningEventRow) -> LearningEvent:
        return LearningEvent(
            sequence=row.sequence,
            event_type=row.event_type,
            payload=json.loads(row.payload_json),
            created_at=_required_utc(row.created_at),
        )
