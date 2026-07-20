"""Contracts for ranking evaluated policy candidates without auto-promotion."""

from typing import Any, Literal

from pydantic import Field

from mllminal.contracts import Contract, new_id


class AutoMLMetric(Contract):
    candidate_name: str = Field(min_length=1, max_length=128)
    parameters: dict[str, Any] = Field(default_factory=dict)
    mean_reward: float
    safe_action_rate: float = Field(ge=0.0, le=1.0)
    invalid_action_rate: float = Field(ge=0.0, le=1.0)
    sample_count: int = Field(ge=1)


class AutoMLRequest(Contract):
    metrics: list[AutoMLMetric] = Field(min_length=1, max_length=100)
    minimum_safe_action_rate: float = Field(default=0.95, ge=0.0, le=1.0)
    maximum_invalid_action_rate: float = Field(default=0.05, ge=0.0, le=1.0)
    max_candidates: int = Field(default=10, ge=1, le=100)


class AutoMLCandidate(Contract):
    id: str = Field(default_factory=new_id)
    candidate_name: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    mean_reward: float
    safe_action_rate: float
    invalid_action_rate: float
    sample_count: int
    eligible_for_review: bool
    auto_promoted: Literal[False] = False


class AutoMLResult(Contract):
    candidates: list[AutoMLCandidate] = Field(default_factory=list)
    selected_candidate_id: str | None = None
    promotion_requires_explicit_approval: Literal[True] = True
