"""Contracts for safe, reviewable proactive suggestions."""

from typing import Literal

from pydantic import Field

from mllminal.contracts import Contract
from mllminal.mining.contracts import MiningRequest


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
