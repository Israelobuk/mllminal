"""Local-only visual observation storage and deterministic verification."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from mllminal.verification.contracts import (
    LocalVisualObservation,
    VisualVerificationRequest,
    VisualVerificationResult,
)


class LocalVisualVerificationService:
    def __init__(self, data_dir: Path, *, history_limit: int = 128) -> None:
        self.path = data_dir / "visual-verification.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.history_limit = history_limit

    def observe(self, observation: LocalVisualObservation) -> LocalVisualObservation:
        canonical = observation.model_dump(exclude={"fingerprint"}, mode="json")
        fingerprint = hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        recorded = observation.model_copy(update={"fingerprint": fingerprint})
        history = self._history()
        history.append(recorded)
        history = history[-self.history_limit :]
        self.path.write_text(
            "".join(item.model_dump_json() + "\n" for item in history), encoding="utf-8"
        )
        return recorded

    def latest(self) -> LocalVisualObservation | None:
        history = self._history()
        return history[-1] if history else None

    def verify(self, request: VisualVerificationRequest) -> VisualVerificationResult:
        actual = {
            (element.role, element.semantic_name): element.state
            for element in request.observation.elements
        }
        matched: list[str] = []
        missing: list[str] = []
        for anchor in request.expected:
            key = (anchor.role, anchor.semantic_name)
            label = f"{anchor.role}:{anchor.semantic_name}"
            if key not in actual or (anchor.state is not None and actual[key] != anchor.state):
                missing.append(label)
            else:
                matched.append(label)
        succeeded = bool(matched) if request.mode.value == "any" else not missing
        reason = (
            "expected visual anchors matched locally"
            if succeeded
            else "expected visual anchors did not match the local observation"
        )
        return VisualVerificationResult(
            succeeded=succeeded,
            reason=reason,
            matched=matched,
            missing=missing,
            observed={
                "application": request.observation.application,
                "window_class": request.observation.window_class,
                "fingerprint": request.observation.fingerprint,
                "element_count": len(request.observation.elements),
            },
        )

    def _history(self) -> list[LocalVisualObservation]:
        if not self.path.exists():
            return []
        return [
            LocalVisualObservation.model_validate_json(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
