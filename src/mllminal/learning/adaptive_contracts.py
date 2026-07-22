"""Typed, privacy-safe records for deterministic adaptive execution."""

from datetime import datetime
from typing import Any

from pydantic import Field, field_validator

from mllminal.contracts import Contract, new_id, utc_now

_FORBIDDEN_MARKERS = ("password", "cookie", "token", "secret", "recovery", "private key")


class AdaptiveBackendCandidate(Contract):
    backend: str
    available: bool = True
    permission_granted: bool = True
    verification_available: bool = True
    consequence_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    latency_ms: float | None = Field(default=None, ge=0.0)
    fragility: float = Field(default=0.0, ge=0.0, le=1.0)


class RejectedBackend(Contract):
    backend: str
    reason: str


class AdaptiveExecutionRequest(Contract):
    workflow_run_id: str
    workflow_step_id: str
    application_profile_id: str
    abstract_action: str
    target_signature: str
    candidates: list[AdaptiveBackendCandidate] = Field(min_length=1)
    safety_filters_applied: list[str] = Field(default_factory=list)
    policy_version: str = "deterministic-profile-policy-v1"

    @field_validator("abstract_action", "target_signature")
    @classmethod
    def reject_sensitive_semantics(cls, value: str) -> str:
        lowered = value.casefold()
        if any(marker in lowered for marker in _FORBIDDEN_MARKERS):
            raise ValueError("adaptive decision contains prohibited credential material")
        if len(value) > 256:
            raise ValueError("adaptive decision field is too long")
        return value


class AdaptiveExecutionDecision(Contract):
    decision_id: str = Field(default_factory=new_id)
    workflow_run_id: str
    workflow_step_id: str
    application_profile_id: str
    abstract_action: str
    target_signature: str
    eligible_backends: list[str] = Field(default_factory=list)
    rejected_backends: list[RejectedBackend] = Field(default_factory=list)
    selected_backend: str | None = None
    reliability_snapshot: dict[str, dict[str, Any]] = Field(default_factory=dict)
    safety_filters_applied: list[str] = Field(default_factory=list)
    policy_version: str
    decision_reason: str
    clarification_required: bool = False
    created_at: datetime = Field(default_factory=utc_now)
    execution_outcome: str | None = None
    verification_outcome: str | None = None
    reward_signal_id: str | None = None
