import hashlib
from pathlib import Path

import pytest

from mllminal.learning.active_policy_registry import (
    ActivePolicyRegistry,
    ActivePolicyStatus,
    ActivePolicyValidationError,
)
from mllminal.learning.contracts import PolicyDomain
from mllminal.learning.replay import LearningRepository


def _setup(tmp_path: Path) -> tuple[LearningRepository, ActivePolicyRegistry]:
    repository = LearningRepository(tmp_path / "learning.db")
    repository.initialize()
    return repository, ActivePolicyRegistry(repository, tmp_path / "checkpoints")


def _candidate(
    repository: LearningRepository, root: Path, domain: PolicyDomain, version: str
) -> str:
    artifact = root / f"{version}.pt"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(f"artifact-{version}".encode())
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    policy = repository.create_policy_version(
        checkpoint_sha256=digest,
        policy_domain=domain,
        feature_schema_version="training_features_v1",
    )
    target = root / f"{policy.name}.pt"
    artifact.replace(target)
    return policy.id


def test_active_bindings_are_independent_per_domain_and_restart_durable(tmp_path: Path) -> None:
    repository, registry = _setup(tmp_path)
    backend = _candidate(
        repository, tmp_path / "checkpoints", PolicyDomain.BACKEND_RANKING, "backend"
    )
    suggestion = _candidate(
        repository, tmp_path / "checkpoints", PolicyDomain.SUGGESTION_RANKING, "suggestion"
    )

    backend_binding = registry.activate(
        backend, activated_by="operator", idempotency_key="activate-backend"
    )
    suggestion_binding = registry.activate(
        suggestion, activated_by="operator", idempotency_key="activate-suggestion"
    )

    assert backend_binding.status is ActivePolicyStatus.ACTIVE
    assert suggestion_binding.status is ActivePolicyStatus.ACTIVE
    assert registry.active(PolicyDomain.BACKEND_RANKING).binding_id == backend_binding.binding_id
    assert (
        registry.active(PolicyDomain.SUGGESTION_RANKING).binding_id == suggestion_binding.binding_id
    )

    restarted = ActivePolicyRegistry(
        LearningRepository(tmp_path / "learning.db"), tmp_path / "checkpoints"
    )
    restarted.repository.initialize()
    assert restarted.active(PolicyDomain.BACKEND_RANKING).candidate_id == backend
    assert restarted.active(PolicyDomain.SUGGESTION_RANKING).candidate_id == suggestion


def test_shadow_binding_coexists_without_replacing_active_binding(tmp_path: Path) -> None:
    repository, registry = _setup(tmp_path)
    active = _candidate(
        repository, tmp_path / "checkpoints", PolicyDomain.SUGGESTION_RANKING, "active"
    )
    shadow = _candidate(
        repository, tmp_path / "checkpoints", PolicyDomain.SUGGESTION_RANKING, "shadow"
    )
    registry.activate(active, activated_by="operator", idempotency_key="active")

    shadow_binding = registry.activate(
        shadow,
        activated_by="operator",
        idempotency_key="shadow",
        mode=ActivePolicyStatus.SHADOW,
    )

    assert shadow_binding.status is ActivePolicyStatus.SHADOW
    assert registry.active(PolicyDomain.SUGGESTION_RANKING).candidate_id == active
    assert len(registry.list(PolicyDomain.SUGGESTION_RANKING)) == 2


def test_second_active_binding_supersedes_and_rollback_restores_previous(tmp_path: Path) -> None:
    repository, registry = _setup(tmp_path)
    first = _candidate(
        repository, tmp_path / "checkpoints", PolicyDomain.VERIFICATION_RANKING, "first"
    )
    second = _candidate(
        repository, tmp_path / "checkpoints", PolicyDomain.VERIFICATION_RANKING, "second"
    )
    first_binding = registry.activate(first, activated_by="operator", idempotency_key="first")
    second_binding = registry.activate(second, activated_by="operator", idempotency_key="second")

    assert registry.active(PolicyDomain.VERIFICATION_RANKING).candidate_id == second
    assert registry.get(first_binding.binding_id).status is ActivePolicyStatus.SUPERSEDED

    restored = registry.rollback(
        PolicyDomain.VERIFICATION_RANKING,
        reason="safety rollback",
        idempotency_key="rollback-verification",
    )

    assert restored.binding_id == first_binding.binding_id
    assert registry.active(PolicyDomain.VERIFICATION_RANKING).candidate_id == first
    assert registry.get(second_binding.binding_id).status is ActivePolicyStatus.ROLLED_BACK


def test_invalid_artifact_digest_and_schema_never_create_binding(tmp_path: Path) -> None:
    repository, registry = _setup(tmp_path)
    candidate = _candidate(
        repository, tmp_path / "checkpoints", PolicyDomain.BACKEND_RANKING, "invalid"
    )
    policy = repository.get_policy_version(candidate)
    (tmp_path / "checkpoints" / f"{policy.name}.pt").write_bytes(b"tampered")

    with pytest.raises(ActivePolicyValidationError, match="digest"):
        registry.activate(candidate, activated_by="operator", idempotency_key="bad-digest")
    invalid_digest = registry.list()[0]
    assert invalid_digest.status is ActivePolicyStatus.INVALID
    assert "digest" in (invalid_digest.status_reason or "")

    clean = _candidate(repository, tmp_path / "checkpoints", PolicyDomain.REPAIR_RANKING, "schema")
    with pytest.raises(ActivePolicyValidationError, match="feature schema"):
        registry.activate(
            clean,
            activated_by="operator",
            idempotency_key="bad-schema",
            feature_schema_version="unsupported_features_v99",
        )
    invalid_bindings = registry.list()
    assert len(invalid_bindings) == 2
    assert all(item.status is ActivePolicyStatus.INVALID for item in invalid_bindings)


def test_activation_is_idempotent_and_disable_keeps_deterministic_fallback(tmp_path: Path) -> None:
    repository, registry = _setup(tmp_path)
    candidate = _candidate(
        repository, tmp_path / "checkpoints", PolicyDomain.CLARIFICATION_POLICY, "idempotent"
    )

    first = registry.activate(candidate, activated_by="operator", idempotency_key="same-key")
    repeated = registry.activate(candidate, activated_by="operator", idempotency_key="same-key")
    disabled = registry.disable(
        PolicyDomain.CLARIFICATION_POLICY,
        reason="manual safety pause",
        idempotency_key="disable-clarification",
    )

    assert repeated.binding_id == first.binding_id
    assert disabled.status is ActivePolicyStatus.INACTIVE
    assert registry.active(PolicyDomain.CLARIFICATION_POLICY) is None
