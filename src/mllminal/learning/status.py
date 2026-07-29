"""Aggregated, safety-oriented active-policy runtime status."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mllminal.learning.active_policy_registry import (
    LIVE_ADVISORY_POLICY_DOMAINS,
    ActivePolicyRegistry,
)
from mllminal.learning.contracts import PolicyDomain
from mllminal.learning.offline_features import TrainingFeatureEncoder
from mllminal.learning.replay import LearningRepository
from mllminal.learning.runtime_adapter import ActivePolicyRuntimeAdapter


class PolicyRuntimeStatusService:
    """Project every domain's runtime posture without changing policy state."""

    def __init__(self, repository: LearningRepository, checkpoint_root: Path) -> None:
        self.repository = repository
        self.registry = ActivePolicyRegistry(repository, checkpoint_root)
        self.checkpoint_root = checkpoint_root

    def snapshot(self) -> dict[str, Any]:
        settings = self.repository.get_settings()
        domains: dict[str, dict[str, Any]] = {}
        for domain in PolicyDomain:
            if domain in LIVE_ADVISORY_POLICY_DOMAINS:
                domains[domain.value] = self._live_status(domain)
            else:
                bindings = self.registry.list(domain)
                active = self.registry.active(domain)
                domains[domain.value] = {
                    "policy_domain": domain.value,
                    "active": False,
                    "shadow": any(binding.status.value == "SHADOW" for binding in bindings),
                    "shadow_only": True,
                    "advisory_only": True,
                    "active_binding_present": active is not None,
                    "shadow_binding_count": sum(
                        binding.status.value == "SHADOW" for binding in bindings
                    ),
                    "fallback_reason": (
                        "domain is shadow-only until a live runtime is integrated"
                        if active is None
                        else "active binding is ignored because domain is shadow-only"
                    ),
                    "automatic_promotion_enabled": False,
                    "automatic_retraining_enabled": False,
                }
        return {
            "domains": domains,
            "live_runtime_domains": sorted(domain.value for domain in LIVE_ADVISORY_POLICY_DOMAINS),
            "shadow_only_domains": sorted(
                domain.value
                for domain in PolicyDomain
                if domain not in LIVE_ADVISORY_POLICY_DOMAINS
            ),
            "advisory_only": True,
            "deterministic_safety_authoritative": True,
            "online_training_enabled": False,
            "automatic_promotion_enabled": settings.automatic_promotion_enabled,
            "automatic_retraining_enabled": False,
        }

    def _live_status(self, domain: PolicyDomain) -> dict[str, Any]:
        encoder = TrainingFeatureEncoder.for_domain(domain)
        adapter = ActivePolicyRuntimeAdapter(
            self.registry,
            self.checkpoint_root,
            policy_domain=domain,
            expected_feature_schema_version=encoder.schema_version,
            expected_input_dimension=encoder.dimension,
        )
        result = adapter.status().as_dict()
        result["shadow_only"] = False
        result["advisory_only"] = True
        result["automatic_promotion_enabled"] = False
        result["automatic_retraining_enabled"] = False
        return result


__all__ = ["PolicyRuntimeStatusService"]
