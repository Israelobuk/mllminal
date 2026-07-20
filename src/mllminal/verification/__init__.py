"""Local-only visual verification primitives."""

from mllminal.verification.contracts import (
    LocalVisualObservation,
    VisualAnchor,
    VisualVerificationRequest,
    VisualVerificationResult,
)
from mllminal.verification.service import LocalVisualVerificationService

__all__ = [
    "LocalVisualObservation",
    "LocalVisualVerificationService",
    "VisualAnchor",
    "VisualVerificationRequest",
    "VisualVerificationResult",
]
