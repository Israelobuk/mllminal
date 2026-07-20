"""Contracts for bounded local screenshot capture and visual verification."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, field_validator

from mllminal.contracts import Contract, new_id, utc_now


class VisualMatchMode(StrEnum):
    ALL = "all"
    ANY = "any"


class FrameCaptureMode(StrEnum):
    ACTIVE_WINDOW = "active_window"
    BOUNDED_APPLICATION = "bounded_application"
    USER_SELECTED_REGION = "user_selected_region"
    VERIFICATION_FRAME = "verification_frame"
    DEMONSTRATION_FALLBACK = "demonstration_fallback"


class FrameRegion(Contract):
    left: int = Field(ge=0)
    top: int = Field(ge=0)
    width: int = Field(gt=0, le=8192)
    height: int = Field(gt=0, le=8192)


class VisualElement(Contract):
    """A semantic UI anchor from local UIA/OCR, never raw image content."""

    role: str = Field(min_length=1, max_length=64)
    semantic_name: str = Field(min_length=1, max_length=128)
    state: str | None = Field(default=None, max_length=64)
    bounds: tuple[float, float, float, float] | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)

    @field_validator("semantic_name")
    @classmethod
    def reject_sensitive_names(cls, value: str) -> str:
        if any(term in value.casefold() for term in ("password", "token", "cookie", "secret")):
            raise ValueError("visual anchors cannot contain credential-oriented names")
        return value


class WindowFrame(Contract):
    id: str = Field(default_factory=new_id)
    captured_at: datetime = Field(default_factory=utc_now)
    path: str
    application: str
    window_class: str = "unknown"
    mode: FrameCaptureMode
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    temporary: bool = True


class VisionRequest(Contract):
    mode: FrameCaptureMode = FrameCaptureMode.ACTIVE_WINDOW
    region: FrameRegion | None = None
    sensitive_regions: list[FrameRegion] = Field(default_factory=list, max_length=64)
    expected: list["VisualAnchor"] = Field(default_factory=list, max_length=256)
    match_mode: VisualMatchMode = VisualMatchMode.ALL
    debug_retention_seconds: int = Field(default=0, ge=0, le=300)


class VisionProviderResult(Contract):
    provider: str
    elements: list[VisualElement] = Field(default_factory=list, max_length=256)
    confidence: float = Field(default=0, ge=0, le=1)
    error_visible: bool = False
    loading_visible: bool = False
    dialog_visible: bool = False
    unsupported_reason: str | None = None


class LocalVisualObservation(Contract):
    id: str = Field(default_factory=new_id)
    observed_at: datetime = Field(default_factory=utc_now)
    source: Literal["local"] = "local"
    application: str = Field(min_length=1, max_length=128)
    window_class: str = Field(default="unknown", min_length=1, max_length=128)
    capture_mode: FrameCaptureMode = FrameCaptureMode.ACTIVE_WINDOW
    elements: list[VisualElement] = Field(default_factory=list, max_length=256)
    provider: str = "unknown"
    confidence: float = Field(default=0, ge=0, le=1)
    error_visible: bool = False
    loading_visible: bool = False
    dialog_visible: bool = False
    unsupported_reason: str | None = None
    frame_deleted: bool = True
    fingerprint: str | None = None
    uploaded: Literal[False] = False


class VisualAnchor(Contract):
    role: str = Field(min_length=1, max_length=64)
    semantic_name: str = Field(min_length=1, max_length=128)
    state: str | None = Field(default=None, max_length=64)

    @field_validator("semantic_name")
    @classmethod
    def reject_sensitive_names(cls, value: str) -> str:
        if any(term in value.casefold() for term in ("password", "token", "cookie", "secret")):
            raise ValueError("visual anchors cannot contain credential-oriented names")
        return value


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


class VisionInspectionResult(Contract):
    """A bounded local inspection and its optional deterministic verification."""

    observation: LocalVisualObservation
    verification: VisualVerificationResult | None = None
