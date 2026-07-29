"""Shared, bounded loading and local inference for active advisory policies."""

from __future__ import annotations

import hashlib
import pickle
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch

from mllminal.learning.active_policy_registry import ActivePolicyRegistry
from mllminal.learning.contracts import (
    ACTION_SPACE_VERSION,
    ActivePolicyBinding,
    ActivePolicyStatus,
    PolicyDomain,
)
from mllminal.learning.offline_training import (
    OfflineCandidateCheckpointError,
    OfflineCandidateModel,
    load_offline_candidate,
)

DEFAULT_MAX_ROWS = 32
DEFAULT_MAX_INFERENCE_SECONDS = 0.050
DEFAULT_MAX_ARTIFACT_BYTES = 16 * 1024 * 1024


class RuntimePolicyUnavailable(ValueError):
    """Raised when an active advisory artifact cannot be used safely."""


@dataclass(frozen=True)
class RuntimePolicyStatus:
    policy_domain: str
    status: str = ActivePolicyStatus.INACTIVE.value
    active: bool = False
    advisory_only: bool = True
    binding_id: str | None = None
    candidate_id: str | None = None
    artifact_digest: str | None = None
    feature_schema_version: str | None = None
    action_schema_version: str | None = None
    schema_valid: bool = False
    fallback_reason: str | None = None
    max_rows: int = DEFAULT_MAX_ROWS
    max_inference_seconds: float = DEFAULT_MAX_INFERENCE_SECONDS
    automatic_promotion_enabled: bool = False
    automatic_retraining_enabled: bool = False

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class LoadedRuntimePolicy:
    binding: ActivePolicyBinding
    model: OfflineCandidateModel


class ActivePolicyRuntimeAdapter:
    """Load exactly one active binding and run a bounded CPU-only artifact."""

    def __init__(
        self,
        registry: ActivePolicyRegistry,
        artifact_root: Path,
        *,
        policy_domain: PolicyDomain,
        expected_feature_schema_version: str,
        expected_input_dimension: int,
        expected_action_schema_version: str = ACTION_SPACE_VERSION,
        runtime_version: str = "runtime_v1",
        max_rows: int = DEFAULT_MAX_ROWS,
        max_inference_seconds: float = DEFAULT_MAX_INFERENCE_SECONDS,
        max_artifact_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES,
    ) -> None:
        if max_rows < 1:
            raise ValueError("max_rows must be positive")
        if max_inference_seconds <= 0.0:
            raise ValueError("max_inference_seconds must be positive")
        if max_artifact_bytes < 1:
            raise ValueError("max_artifact_bytes must be positive")
        self.registry = registry
        self.artifact_root = artifact_root.resolve()
        self.policy_domain = policy_domain
        self.expected_feature_schema_version = expected_feature_schema_version
        self.expected_input_dimension = expected_input_dimension
        self.expected_action_schema_version = expected_action_schema_version
        self.runtime_version = runtime_version
        self.max_rows = max_rows
        self.max_inference_seconds = max_inference_seconds
        self.max_artifact_bytes = max_artifact_bytes
        self._last_fallback_reason: str | None = None
        self._loaded: tuple[str, str, OfflineCandidateModel] | None = None

    def status(self) -> RuntimePolicyStatus:
        binding = self.registry.active(self.policy_domain)
        try:
            self.load()
        except RuntimePolicyUnavailable as error:
            self._last_fallback_reason = str(error)
            return self._status(binding=binding)
        return self._status(binding=binding, active=True, schema_valid=True)

    def load(self) -> LoadedRuntimePolicy:
        binding = self.registry.active(self.policy_domain)
        if binding is None:
            raise self._unavailable("no active policy binding")
        if binding.status is not ActivePolicyStatus.ACTIVE:
            raise self._unavailable("active policy binding is not ACTIVE")
        try:
            candidate = self.registry.repository.get_policy_version(binding.candidate_id)
        except KeyError as error:
            raise self._unavailable("active policy candidate is unavailable") from error
        if candidate.lifecycle.value != "ACTIVE":
            raise self._unavailable("active policy candidate is not ACTIVE")
        if binding.runtime_version != self.runtime_version:
            raise self._unavailable("runtime version is incompatible")
        if binding.feature_schema_version != self.expected_feature_schema_version:
            raise self._unavailable("feature schema is incompatible")
        if binding.action_schema_version != self.expected_action_schema_version:
            raise self._unavailable("action schema is incompatible")
        path = self._artifact_path(binding.artifact_path)
        try:
            if path.stat().st_size > self.max_artifact_bytes:
                raise self._unavailable("artifact size budget exceeded")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as error:
            raise self._unavailable("policy artifact is unavailable") from error
        if digest != binding.artifact_digest:
            raise self._unavailable("artifact digest mismatch")
        cache_key = (binding.binding_id, digest)
        if self._loaded is None or self._loaded[:2] != cache_key:
            try:
                model = load_offline_candidate(path)
            except (
                OSError,
                RuntimeError,
                ValueError,
                TypeError,
                EOFError,
                pickle.UnpicklingError,
                OfflineCandidateCheckpointError,
            ) as error:
                raise self._unavailable("candidate artifact is invalid") from error
            if model.feature_schema_version != binding.feature_schema_version:
                raise self._unavailable("artifact feature schema is incompatible")
            input_layer = model.network.layers[0]
            if not hasattr(input_layer, "in_features"):
                raise self._unavailable("artifact input layer is invalid")
            if input_layer.in_features != self.expected_input_dimension:
                raise self._unavailable("artifact feature dimension is incompatible")
            if not model.action_labels or len(set(model.action_labels)) != len(model.action_labels):
                raise self._unavailable("artifact action labels are invalid")
            self._loaded = (binding.binding_id, digest, model)
        self._last_fallback_reason = None
        return LoadedRuntimePolicy(binding=binding, model=self._loaded[2])

    def infer(self, feature_rows: Sequence[Sequence[float]]) -> tuple[tuple[float, ...], ...]:
        if len(feature_rows) > self.max_rows:
            raise self._unavailable("inference row budget exceeded")
        if not feature_rows:
            return ()
        loaded = self.load()
        try:
            features = torch.tensor(feature_rows, dtype=torch.float32)
        except (TypeError, ValueError, RuntimeError) as error:
            raise self._unavailable("inference features are invalid") from error
        if features.ndim != 2 or features.shape[1] != self.expected_input_dimension:
            raise self._unavailable("inference feature shape is invalid")
        if not torch.isfinite(features).all():
            raise self._unavailable("inference features are not finite")
        started = time.perf_counter()
        try:
            with torch.inference_mode():
                output = loaded.model.network(features)
        except (RuntimeError, ValueError, TypeError) as error:
            raise self._unavailable("inference failed") from error
        if time.perf_counter() - started > self.max_inference_seconds:
            raise self._unavailable("inference budget exceeded")
        if output.ndim != 2 or output.shape[0] != len(feature_rows):
            raise self._unavailable("inference output shape is invalid")
        if not torch.isfinite(output).all():
            raise self._unavailable("inference output is not finite")
        rows = output.detach().cpu().tolist()
        if any(len(row) != len(loaded.model.action_labels) for row in rows):
            raise self._unavailable("inference output dimensions are invalid")
        return tuple(tuple(min(max(float(score), 0.0), 1.0) for score in row) for row in rows)

    def _artifact_path(self, artifact_path: str) -> Path:
        path = (self.artifact_root / artifact_path).resolve()
        try:
            path.relative_to(self.artifact_root)
        except ValueError as error:
            raise self._unavailable("artifact path escapes learning directory") from error
        return path

    def _status(
        self,
        *,
        binding: ActivePolicyBinding | None,
        active: bool = False,
        schema_valid: bool = False,
    ) -> RuntimePolicyStatus:
        return RuntimePolicyStatus(
            policy_domain=self.policy_domain.value,
            status=binding.status.value if binding else ActivePolicyStatus.INACTIVE.value,
            active=active,
            binding_id=binding.binding_id if binding else None,
            candidate_id=binding.candidate_id if binding else None,
            artifact_digest=binding.artifact_digest if binding else None,
            feature_schema_version=binding.feature_schema_version if binding else None,
            action_schema_version=binding.action_schema_version if binding else None,
            schema_valid=schema_valid,
            fallback_reason=self._last_fallback_reason,
            max_rows=self.max_rows,
            max_inference_seconds=self.max_inference_seconds,
        )

    def _unavailable(self, reason: str) -> RuntimePolicyUnavailable:
        self._last_fallback_reason = reason
        return RuntimePolicyUnavailable(reason)


__all__ = [
    "ActivePolicyRuntimeAdapter",
    "LoadedRuntimePolicy",
    "RuntimePolicyStatus",
    "RuntimePolicyUnavailable",
]
