"""Contracts for deterministic, metadata-only visual verification."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, field_validator

from mllminal.contracts import Contract, new_id, utc_now


class VisualMatchMode(StrEnum):
    ALL = "all"
    ANY = "any"


class VisualElement(Contract):
    """A semantic UI anchor supplied by a local adapter, never a raw screenshot."""

    role: str = Field(min_length=1, max_length=64)
    semantic_name: str = Field(min_length=1, max_length=128)
    state: str | None = Field(default=None, max_length=64)
    bounds: tuple[float, float, float, float] | None = None

    @field_validator("semantic_name")
    @classmethod
    def reject_sensitive_names(cls, value: str) -> str:
        if any(term in value.casefold() for term in ("password", "token", "cookie", "secret")):
            raise ValueError("visual anchors cannot contain credential-oriented names")
        return value


class LocalVisualObservation(Contract):
    id: str = Field(default_factory=new_id)
    observed_at: datetime = Field(default_factory=utc_now)
    source: Literal["local"] = "local"
    application: str = Field(min_length=1, max_length=128)
    window_class: str = Field(default="unknown", min_length=1, max_length=128)
    elements: list[VisualElement] = Field(default_factory=list, max_length=256)
    fingerprint: str | None = None
    uploaded: Literal[False] = False


class VisualAnchor(Contract):
    role: str = Field(min_length=1, max_length=64)
    semantic_name: str = Field(min_length=1, max_length=128)
    state: str | None = Field(default=None, max_length=64)


class VisualVerificationRequest(Contract):
    observation: LocalVisualObservation
    expected: list[VisualAnchor] = Field(min_length=1, max_length=256)
    mode: VisualMatchMode = VisualMatchMode.ALL


class VisualVerificationResult(Contract):
    succeeded: bool
    reason: str
    matched: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    observed: dict[str, Any] = Field(default_factory=dict)
    local_only: Literal[True] = True
