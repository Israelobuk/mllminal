"""Versioned contracts for safe, local policy learning."""

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from math import isclose
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from uuid6 import uuid7

FEATURE_VERSION: Literal["features_v1"] = "features_v1"
ACTION_SPACE_VERSION: Literal["actions_v1"] = "actions_v1"
FEATURE_DIM = 15
ACTION_DIM = 9
DEFAULT_CONFIDENCE = 0.65


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid7())


class LearningContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["v1"] = "v1"

    @model_validator(mode="after")
    def validate_identity_and_time(self) -> Self:
        entity_id = getattr(self, "id", None)
        if entity_id is not None:
            try:
                parsed_id = UUID(entity_id)
            except (ValueError, AttributeError) as error:
                raise ValueError("entity id must be UUIDv7") from error
            if parsed_id.version != 7:
                raise ValueError("entity id must be UUIDv7")
        for field_name in self.__class__.model_fields:
            value = getattr(self, field_name)
            if isinstance(value, datetime) and (
                value.tzinfo is None or value.utcoffset() != timedelta(0)
            ):
                raise ValueError(f"{field_name} must be timezone-aware UTC")
        return self


class PolicyAction(StrEnum):
    ANSWER_DIRECTLY = "ANSWER_DIRECTLY"
    INSPECT_WORKSPACE = "INSPECT_WORKSPACE"
    READ_PROJECT_FILE = "READ_PROJECT_FILE"
    ASK_USER = "ASK_USER"
    REQUEST_APPROVAL = "REQUEST_APPROVAL"
    EXECUTE_APPROVED_TOOL = "EXECUTE_APPROVED_TOOL"
    VERIFY_RESULT = "VERIFY_RESULT"
    RETRY = "RETRY"
    STOP_SAFELY = "STOP_SAFELY"


class PolicyCheckpoint(StrEnum):
    REQUEST_RECEIVED = "REQUEST_RECEIVED"
    PLAN_READY = "PLAN_READY"
    APPROVAL_GRANTED = "APPROVAL_GRANTED"
    TOOL_RESULT_AVAILABLE = "TOOL_RESULT_AVAILABLE"
    RECOVERABLE_FAILURE = "RECOVERABLE_FAILURE"


class ExperienceStatus(StrEnum):
    PENDING = "PENDING"
    ELIGIBLE = "ELIGIBLE"
    EXCLUDED = "EXCLUDED"
    CONSUMED = "CONSUMED"


class RunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class PolicyLifecycle(StrEnum):
    CANDIDATE = "CANDIDATE"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"
    ROLLED_BACK = "ROLLED_BACK"
    REJECTED = "REJECTED"


class PromotionOutcome(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PolicyState(LearningContract):
    id: str = Field(default_factory=new_id)
    task_id: str
    feature_version: Literal["features_v1"] = FEATURE_VERSION
    action_space_version: Literal["actions_v1"] = ACTION_SPACE_VERSION
    features: tuple[float, ...] = Field(min_length=FEATURE_DIM, max_length=FEATURE_DIM)
    action_mask: tuple[bool, ...] = Field(min_length=ACTION_DIM, max_length=ACTION_DIM)
    created_at: datetime = Field(default_factory=utc_now)


class PolicyDecision(LearningContract):
    id: str = Field(default_factory=new_id)
    task_id: str
    state_id: str | None = None
    selected_action: PolicyAction
    confidence: float = Field(default=DEFAULT_CONFIDENCE, ge=0.0, le=1.0)
    policy_version_id: str | None = None
    scores: tuple[float, ...] | None = Field(
        default=None, min_length=ACTION_DIM, max_length=ACTION_DIM
    )
    used_safe_fallback: bool = False
    created_at: datetime = Field(default_factory=utc_now)


class RewardBreakdown(LearningContract):
    verified_completion: float = 0.0
    verification_passed: float = 0.0
    tool_succeeded: float = 0.0
    user_accepted: float = 0.0
    efficient_execution: float = 0.0
    successful_recovery: float = 0.0
    correct_safe_stop: float = 0.0
    user_corrected: float = 0.0
    approval_rejected: float = 0.0
    tool_failed: float = 0.0
    verification_failed: float = 0.0
    invalid_policy_action: float = 0.0
    unauthorized_action: float = 0.0
    unnecessary_retry: float = 0.0
    repeated_loop: float = 0.0
    provider_failure: float = 0.0
    task_failure: float = 0.0
    total: float = 0.0

    @model_validator(mode="after")
    def total_equals_component_sum(self) -> Self:
        component_sum = sum(
            value
            for name, value in self.__dict__.items()
            if name not in {"schema_version", "total"}
        )
        if not isclose(self.total, component_sum, abs_tol=1e-12):
            raise ValueError("reward total must equal the sum of reward components")
        return self


class ExperienceOutcome(LearningContract):
    terminal: bool
    task_completed: bool = False
    verification_passed: bool = False
    tool_succeeded: bool = False
    user_accepted: bool = False
    efficient_execution: bool = False
    successful_recovery: bool = False
    correct_safe_stop: bool = False
    user_corrected: bool = False
    approval_rejected: bool = False
    tool_failed: bool = False
    verification_failed: bool = False
    invalid_policy_action: bool = False
    unauthorized_action: bool = False
    unnecessary_retry: bool = False
    repeated_loop: bool = False
    provider_failure: bool = False
    task_failed: bool = False


class ExperienceRecord(LearningContract):
    id: str = Field(default_factory=new_id)
    task_id: str
    decision_id: str
    idempotency_key: str
    selected_action: PolicyAction | None
    outcome: ExperienceOutcome
    reward: RewardBreakdown | None
    status: ExperienceStatus = ExperienceStatus.PENDING
    contains_sensitive_data: bool = False
    contains_raw_data: bool = False
    synthetic: bool = False
    training_enabled: bool = False
    created_at: datetime = Field(default_factory=utc_now)


class ReplaySample(LearningContract):
    id: str = Field(default_factory=new_id)
    replay_entry_id: int = Field(default=0, ge=0)
    experience_id: str
    features: tuple[float, ...] = Field(min_length=FEATURE_DIM, max_length=FEATURE_DIM)
    action: PolicyAction
    reward: float
    sampled_at: datetime = Field(default_factory=utc_now)


class TrainingRun(LearningContract):
    id: str = Field(default_factory=new_id)
    status: RunStatus = RunStatus.PENDING
    seed: int = 42
    eligible_experience_count: int = Field(default=0, ge=0)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    failure_reason: str | None = None
    replay_entry_ids: tuple[int, ...] = ()
    lifecycle_stage: Literal["COLLECTING", "TRAINING", "EVALUATING"] = "COLLECTING"
    created_at: datetime = Field(default_factory=utc_now)


class EvaluationReport(LearningContract):
    id: str = Field(default_factory=new_id)
    training_run_id: str
    candidate_policy_id: str
    sample_count: int = Field(ge=0)
    mean_reward: float
    safe_action_rate: float = Field(ge=0.0, le=1.0)
    passed: bool
    created_at: datetime = Field(default_factory=utc_now)


class PolicyVersion(LearningContract):
    id: str = Field(default_factory=new_id)
    version: int = Field(ge=0)
    name: str | None = None
    lifecycle: PolicyLifecycle = PolicyLifecycle.CANDIDATE
    feature_version: Literal["features_v1"] = FEATURE_VERSION
    action_space_version: Literal["actions_v1"] = ACTION_SPACE_VERSION
    checkpoint_sha256: str | None = None
    training_run_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class PromotionDecision(LearningContract):
    id: str = Field(default_factory=new_id)
    policy_version_id: str
    evaluation_report_id: str
    outcome: PromotionOutcome
    reason: str
    explicitly_approved: bool = False
    decided_at: datetime = Field(default_factory=utc_now)


class RollbackRecord(LearningContract):
    id: str = Field(default_factory=new_id)
    from_policy_version_id: str
    to_policy_version_id: str
    reason: str
    rolled_back_at: datetime = Field(default_factory=utc_now)


class LearningStatus(LearningContract):
    enabled: bool = True
    automatic_promotion_enabled: bool = False
    active_policy_version_id: str | None = None
    candidate_policy_version_id: str | None = None
    eligible_experience_count: int = Field(default=0, ge=0)
    minimum_experience_count: int = Field(default=100, ge=1)
    replay_capacity: int = Field(default=10_000, ge=1)
    seed: int = 42
    confidence_threshold: float = Field(default=DEFAULT_CONFIDENCE, ge=0.0, le=1.0)
    updated_at: datetime = Field(default_factory=utc_now)
