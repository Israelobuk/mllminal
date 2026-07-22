"""Contracts for safe, reviewable proactive suggestions."""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from mllminal.contracts import Contract, new_id, utc_now
from mllminal.mining.contracts import MiningRequest, WorkflowCandidate


class AssistanceRequest(Contract):
    mining: MiningRequest = Field(default_factory=MiningRequest)
    minimum_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    max_suggestions: int = Field(default=5, ge=1, le=25)


class AssistanceSuggestion(Contract):
    workflow_candidate_id: str
    title: str
    application: str
    summary: str
    occurrences: int = Field(ge=2)
    confidence: float = Field(ge=0.0, le=1.0)
    requires_approval: Literal[True] = True
    auto_executed: Literal[False] = False


class AssistanceResult(Contract):
    suggestions: list[AssistanceSuggestion] = Field(default_factory=list)
    source_event_count: int = Field(ge=0)
    metadata_only: Literal[True] = True


class SuggestionStatus(StrEnum):
    PENDING = "pending"
    ELIGIBLE = "eligible"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DISMISSED = "dismissed"
    SNOOZED = "snoozed"
    DISABLED = "disabled"


class SuggestionFeedbackKind(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    DISMISS = "dismiss"
    SNOOZE = "snooze"
    DISABLE = "disable"


class PreferenceScope(StrEnum):
    GLOBAL = "global"
    APPLICATION = "application"
    WORKFLOW = "workflow"


class UserWorkflowPreference(Contract):
    preference_id: str = Field(default_factory=new_id)
    scope: PreferenceScope
    application: str | None = None
    candidate_id: str | None = None
    enabled: bool = True
    quiet_hours: bool = False
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SuggestionFeedback(Contract):
    feedback_id: str = Field(default_factory=new_id)
    suggestion_id: str
    candidate_id: str
    kind: SuggestionFeedbackKind
    idempotency_key: str
    created_at: datetime = Field(default_factory=utc_now)


class SuggestionRankingDecision(Contract):
    decision_id: str = Field(default_factory=new_id)
    suggestion_id: str
    candidate_id: str
    ranking_score: float
    ranking_components: dict[str, float] = Field(default_factory=dict)
    explanation: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class WorkflowAdaptationProposal(Contract):
    proposal_id: str = Field(default_factory=new_id)
    candidate_id: str
    source_suggestion_id: str
    change_summary: str
    evidence_count: int = Field(ge=0)
    requires_explicit_review: Literal[True] = True
    automatically_promoted: Literal[False] = False
    created_at: datetime = Field(default_factory=utc_now)


class AdaptiveWorkflowSuggestion(Contract):
    suggestion_id: str = Field(default_factory=new_id)
    candidate_id: str
    application: str
    title: str
    summary: str
    source_episode_ids: list[str] = Field(default_factory=list)
    occurrence_count: int = Field(ge=0)
    confidence: float = Field(ge=0.0, le=1.0)
    verification_availability: bool
    emergency_stop_active: bool = False
    permission_preserved: Literal[True] = True
    approval_preserved: Literal[True] = True
    prior_rejection_count: int = Field(default=0, ge=0)
    ranking_score: float
    ranking_components: dict[str, float] = Field(default_factory=dict)
    ranking_explanation: list[str] = Field(default_factory=list)
    eligibility_reasons: list[str] = Field(default_factory=list)
    status: SuggestionStatus = SuggestionStatus.PENDING
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SuggestionProposalRequest(Contract):
    candidate: WorkflowCandidate
    verification_available: bool


class SuggestionFeedbackRequest(Contract):
    kind: SuggestionFeedbackKind


class PreferenceUpdateRequest(Contract):
    preference: UserWorkflowPreference
