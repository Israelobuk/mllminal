"""Local-only visual verification primitives."""

from mllminal.verification.contracts import (
    FrameCaptureMode,
    FrameRegion,
    LocalVisualObservation,
    VisionInspectionResult,
    VisionRequest,
    VisualAnchor,
    VisualVerificationRequest,
    VisualVerificationResult,
)
from mllminal.verification.runtime import LocalVisionRuntime, VisionProvider, WindowsFrameCapture
from mllminal.verification.service import LocalVisualVerificationService

__all__ = [
    "FrameCaptureMode",
    "FrameRegion",
    "LocalVisionRuntime",
    "LocalVisualObservation",
    "LocalVisualVerificationService",
    "VisionInspectionResult",
    "VisionProvider",
    "VisionRequest",
    "VisualAnchor",
    "VisualVerificationRequest",
    "VisualVerificationResult",
    "WindowsFrameCapture",
]
