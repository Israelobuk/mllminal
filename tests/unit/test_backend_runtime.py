from pathlib import Path
from unittest.mock import patch

import torch

from mllminal.learning.active_policy_registry import ActivePolicyRegistry
from mllminal.learning.adaptive import (
    AdaptiveBackendCandidate,
    AdaptiveExecutionRequest,
    AdaptiveExecutionService,
)
from mllminal.learning.backend_runtime import BackendPolicyRuntime
from mllminal.learning.contracts import PolicyDomain
from mllminal.learning.offline_features import TrainingFeatureEncoder
from mllminal.learning.offline_training import (
    OfflineCandidateModel,
    OfflinePolicyNetwork,
    save_offline_candidate,
)
from mllminal.learning.profile_contracts import ApplicationInteractionProfile
from mllminal.learning.profiles import ApplicationInteractionProfileService
from mllminal.learning.replay import LearningRepository


def _request(profile: ApplicationInteractionProfile) -> AdaptiveExecutionRequest:
    return AdaptiveExecutionRequest(
        workflow_run_id="runtime-run",
        workflow_step_id="step-1",
        application_profile_id=profile.profile_id,
        abstract_action="control.invoke",
        target_signature="automation_id:open-button",
        candidates=[
            AdaptiveBackendCandidate(backend="windows.uia"),
            AdaptiveBackendCandidate(backend="local.vision"),
            AdaptiveBackendCandidate(backend="blocked.backend", permission_granted=False),
        ],
    )


def _runtime(
    tmp_path: Path,
) -> tuple[AdaptiveExecutionService, BackendPolicyRuntime, ApplicationInteractionProfile]:
    repository = LearningRepository(tmp_path / "learning.db")
    repository.initialize()
    profile = ApplicationInteractionProfile(
        application_identity="explorer",
        executable_name="explorer.exe",
        stable_automation_ids=["open-button"],
    )
    repository.save_interaction_profile(profile, identity_key="explorer")
    encoder = TrainingFeatureEncoder.for_domain(PolicyDomain.BACKEND_RANKING)
    network = OfflinePolicyNetwork(encoder.dimension, 2, 4).cpu()
    with torch.no_grad():
        network.layers[0].weight.zero_()
        network.layers[0].bias.zero_()
        network.layers[2].weight.zero_()
        network.layers[2].bias.copy_(torch.tensor([-5.0, 5.0]))
    policy = repository.create_policy_version(
        checkpoint_sha256=None,
        policy_domain=PolicyDomain.BACKEND_RANKING,
        feature_schema_version=encoder.schema_version,
    )
    checkpoint_path = tmp_path / "checkpoints" / f"{policy.name}.pt"
    digest = save_offline_candidate(
        OfflineCandidateModel(network, ("windows.uia", "local.vision"), encoder.schema_version),
        checkpoint_path,
    )
    policy = repository.update_policy_checkpoint(policy.id, digest)
    repository.promote_policy(policy.id, reason="test approval", idempotency_key="test-promote")
    ActivePolicyRegistry(repository, tmp_path / "checkpoints").activate(
        policy.id,
        activated_by="test",
        idempotency_key="test-active-backend",
    )
    runtime = BackendPolicyRuntime(repository, tmp_path / "checkpoints")
    return (
        AdaptiveExecutionService(
            repository,
            ApplicationInteractionProfileService(repository),
            policy_runtime=runtime,
        ),
        runtime,
        profile,
    )


def test_promoted_backend_policy_influences_only_eligible_ranking_and_persists_provenance(
    tmp_path: Path,
) -> None:
    service, runtime, profile = _runtime(tmp_path)

    decision = service.decide(_request(profile))

    assert decision.selected_backend == "local.vision"
    assert "blocked.backend" not in decision.advisory_scores
    assert decision.rejected_backends[0].reason == "permission_not_granted"
    assert decision.advisory_policy["active"] is True
    assert decision.advisory_policy["used_in_ranking"] is True
    assert decision.combined_scores["local.vision"] > decision.combined_scores["windows.uia"]
    restored = service.decision(decision.decision_id)
    assert restored.decision_reason == decision.decision_reason
    assert restored.advisory_policy["artifact_digest"] == runtime.status().artifact_digest


def test_digest_failure_falls_back_and_opens_circuit_without_lifecycle_mutation(
    tmp_path: Path,
) -> None:
    service, runtime, profile = _runtime(tmp_path)
    artifact = next((tmp_path / "checkpoints").glob("policy_v*.pt"))
    artifact.write_bytes(artifact.read_bytes() + b"tampered")

    first = service.decide(_request(profile))
    second = service.decide(
        _request(profile).model_copy(update={"workflow_run_id": "runtime-run-2"})
    )
    third = service.decide(
        _request(profile).model_copy(update={"workflow_run_id": "runtime-run-3"})
    )

    assert first.selected_backend == "windows.uia"
    assert first.advisory_scores == {}
    assert third.advisory_policy["circuit_open"] is True
    assert runtime.repository.get_promoted_policy().name == "policy_v1"
    assert runtime.repository.get_promoted_policy().lifecycle.value == "ACTIVE"
    assert second.advisory_policy["last_fallback_reason"] == "checkpoint digest mismatch"


def test_rollback_or_non_backend_active_policy_is_deterministic_fallback(tmp_path: Path) -> None:
    repository = LearningRepository(tmp_path / "learning.db")
    repository.initialize()
    runtime = BackendPolicyRuntime(repository, tmp_path / "checkpoints")

    status = runtime.status()

    assert status.active is False
    assert status.advisory_only is True
    assert status.last_fallback_reason is not None
    assert status.automatic_promotion_enabled is False
    assert status.automatic_retraining_enabled is False


def test_emergency_stop_blocks_active_advisory_influence(tmp_path: Path) -> None:
    service, runtime, profile = _runtime(tmp_path)
    stopped = AdaptiveExecutionService(
        service.repository,
        ApplicationInteractionProfileService(service.repository),
        emergency_stop_active=lambda: True,
        policy_runtime=runtime,
    )

    decision = stopped.decide(_request(profile))

    assert decision.selected_backend is None
    assert decision.advisory_scores == {}
    assert all(item.reason == "emergency_stop_active" for item in decision.rejected_backends)


def test_rollback_to_policy_v0_disables_runtime_without_promoting_or_retraining(
    tmp_path: Path,
) -> None:
    service, runtime, profile = _runtime(tmp_path)
    active = service.repository.get_promoted_policy()
    fallback = next(
        policy for policy in service.repository.list_policy_versions() if policy.version == 0
    )

    service.repository.rollback_policy(
        fallback.id,
        reason="runtime acceptance rollback",
        idempotency_key="runtime-rollback",
    )
    decision = service.decide(_request(profile))

    assert decision.advisory_scores == {}
    assert decision.selected_backend == "windows.uia"
    assert runtime.status().active is False
    assert service.repository.get_promoted_policy().id == fallback.id
    assert service.repository.get_policy_version(active.id).lifecycle.value == "ROLLED_BACK"


def test_low_confidence_advisory_abstains_and_opens_runtime_circuit(
    tmp_path: Path,
) -> None:
    service, runtime, profile = _runtime(tmp_path)
    with patch.object(
        runtime.adapter,
        "infer",
        return_value=((0.55, 0.54), (0.55, 0.54), (0.55, 0.54)),
    ):
        first = service.decide(_request(profile))
        second = service.decide(
            _request(profile).model_copy(update={"workflow_run_id": "low-confidence-2"})
        )
        third = service.decide(
            _request(profile).model_copy(update={"workflow_run_id": "low-confidence-3"})
        )

    assert first.advisory_scores == {}
    assert first.advisory_policy["last_fallback_reason"] == "advisory confidence below threshold"
    assert first.advisory_policy["confidence_threshold"] == 0.65
    assert first.selected_backend == "windows.uia"
    assert second.advisory_scores == {}
    assert third.advisory_policy["circuit_open"] is True
    assert runtime.repository.get_promoted_policy().lifecycle.value == "ACTIVE"
