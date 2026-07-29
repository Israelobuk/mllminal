from pathlib import Path

import torch

from mllminal.learning.active_policy_registry import ActivePolicyRegistry
from mllminal.learning.adaptive import (
    AdaptiveBackendCandidate,
    AdaptiveExecutionRequest,
    AdaptiveExecutionService,
)
from mllminal.learning.backend_runtime import BackendPolicyRuntime
from mllminal.learning.contracts import ActivePolicyStatus, PolicyDomain
from mllminal.learning.offline_features import TrainingFeatureEncoder
from mllminal.learning.offline_training import (
    OfflineCandidateModel,
    OfflinePolicyNetwork,
    save_offline_candidate,
)
from mllminal.learning.profile_contracts import ApplicationInteractionProfile
from mllminal.learning.profiles import ApplicationInteractionProfileService
from mllminal.learning.replay import LearningRepository


def test_shadow_policy_is_persisted_but_cannot_change_live_backend_selection(
    tmp_path: Path,
) -> None:
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
    artifact = tmp_path / "checkpoints" / f"{policy.name}.pt"
    digest = save_offline_candidate(
        OfflineCandidateModel(network, ("windows.uia", "local.vision"), encoder.schema_version),
        artifact,
    )
    policy = repository.update_policy_checkpoint(policy.id, digest)
    binding = ActivePolicyRegistry(repository, tmp_path / "checkpoints").activate(
        policy.id,
        activated_by="test",
        idempotency_key="test-shadow-policy",
        mode=ActivePolicyStatus.SHADOW,
    )
    service = AdaptiveExecutionService(
        repository,
        ApplicationInteractionProfileService(repository),
        shadow_policy_runtime=BackendPolicyRuntime(
            repository,
            tmp_path / "checkpoints",
            shadow_mode=True,
        ),
    )
    decision = service.decide(
        AdaptiveExecutionRequest(
            workflow_run_id="shadow-run",
            workflow_step_id="step-1",
            application_profile_id=profile.profile_id,
            abstract_action="control.invoke",
            target_signature="automation_id:open-button",
            candidates=[
                AdaptiveBackendCandidate(backend="windows.uia"),
                AdaptiveBackendCandidate(backend="local.vision"),
            ],
        )
    )

    assert binding.status is ActivePolicyStatus.SHADOW
    assert decision.selected_backend == "windows.uia"
    assert (
        decision.shadow_advisory_scores["local.vision"]
        > decision.shadow_advisory_scores["windows.uia"]
    )
    assert decision.shadow_selected_backend == "local.vision"
    assert decision.shadow_rank_changed is True
    assert decision.advisory_scores == {}
    assert decision.shadow_policy["shadow"] is True
    assert decision.shadow_policy["used_in_ranking"] is False
    assert decision.shadow_policy["evaluation_only"] is True
    assert "shadow" in decision.decision_reason.casefold()
    restored = service.decision(decision.decision_id)
    assert restored.shadow_selected_backend == "local.vision"
    assert restored.shadow_combined_scores == decision.shadow_combined_scores
