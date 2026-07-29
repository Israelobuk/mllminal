"""Deterministic profile-guided backend selection and outcome learning."""

from collections.abc import Callable

from mllminal.learning.adaptive_contracts import (
    AdaptiveBackendCandidate,
    AdaptiveExecutionDecision,
    AdaptiveExecutionRequest,
    RejectedBackend,
)
from mllminal.learning.backend_runtime import BackendPolicyRuntime, BackendPolicyStatus
from mllminal.learning.offline_collection import training_experience_from_adaptive_decision
from mllminal.learning.profile_contracts import (
    ApplicationInteractionProfile,
    BackendOutcomeRequest,
    BackendReliabilityRecord,
    ProfileOutcome,
)
from mllminal.learning.profiles import (
    INTERACTION_BACKEND_HIERARCHY,
    ApplicationInteractionProfileService,
)
from mllminal.learning.replay import LearningRepository


class AdaptiveExecutionService:
    """Choose only safe backends; learned evidence is advisory and explainable."""

    def __init__(
        self,
        repository: LearningRepository,
        profiles: ApplicationInteractionProfileService,
        *,
        emergency_stop_active: Callable[[], bool] | None = None,
        policy_runtime: BackendPolicyRuntime | None = None,
    ) -> None:
        self.repository = repository
        self.profiles = profiles
        self.emergency_stop_active = emergency_stop_active or (lambda: False)
        self.policy_runtime = policy_runtime or BackendPolicyRuntime(
            repository, repository.database_path.parent / "learning" / "checkpoints"
        )

    def decide(self, request: AdaptiveExecutionRequest) -> AdaptiveExecutionDecision:
        request = AdaptiveExecutionRequest.model_validate(request.model_dump())
        profile = self.profiles.profile(request.application_profile_id)
        rejected: list[RejectedBackend] = []
        eligible: list[AdaptiveBackendCandidate] = []
        filters = ["deterministic_safety_filter", *request.safety_filters_applied]
        emergency = self.emergency_stop_active()
        for candidate in request.candidates:
            if emergency:
                rejected.append(
                    RejectedBackend(backend=candidate.backend, reason="emergency_stop_active")
                )
            elif not candidate.available:
                rejected.append(
                    RejectedBackend(backend=candidate.backend, reason="backend_unavailable")
                )
            elif not candidate.permission_granted:
                rejected.append(
                    RejectedBackend(backend=candidate.backend, reason="permission_not_granted")
                )
            else:
                eligible.append(candidate)
        if emergency:
            filters.append("emergency_stop")

        records = {
            record.backend: record
            for record in self.profiles.reliability(profile.profile_id)
            if record.abstract_action == request.abstract_action
            and record.target_type == self._target_type(request.target_signature)
        }
        deterministic_ranked = sorted(
            eligible,
            key=lambda candidate: self._rank_key(
                candidate, records.get(candidate.backend), profile, request.target_signature
            ),
            reverse=True,
        )
        snapshots = {
            candidate.backend: self._snapshot(
                candidate, records.get(candidate.backend), profile, request.target_signature
            )
            for candidate in deterministic_ranked
        }
        advisory_result = (
            self.policy_runtime.evaluate(request, eligible, profile, records)
            if eligible and not emergency
            else self.policy_runtime.status()
        )
        if isinstance(advisory_result, BackendPolicyStatus):
            advisory_scores: dict[str, float] = {}
            advisory_policy = advisory_result.as_dict()
        else:
            advisory_scores = advisory_result.scores
            advisory_policy = advisory_result.provenance.as_dict()
        advisory_used = bool(advisory_scores)
        weight = self.policy_runtime.advisory_weight if advisory_used else 0.0
        hierarchy = {backend: -index for index, backend in enumerate(INTERACTION_BACKEND_HIERARCHY)}
        deterministic_scores = {
            backend: float(snapshot["score"]) for backend, snapshot in snapshots.items()
        }
        combined_scores = {
            candidate.backend: ((1.0 - weight) * deterministic_scores[candidate.backend])
            + (weight * advisory_scores.get(candidate.backend, 0.5))
            for candidate in deterministic_ranked
        }
        ranked = sorted(
            deterministic_ranked,
            key=lambda candidate: (
                combined_scores[candidate.backend],
                hierarchy.get(candidate.backend, -len(hierarchy)),
                candidate.backend,
            ),
            reverse=True,
        )
        advisory_policy["used_in_ranking"] = advisory_used
        advisory_policy["effective_weight"] = weight
        selected = ranked[0].backend if ranked else None
        clarification = self._clarification_required(
            ranked, snapshots, profile, request.target_signature
        )
        if clarification:
            selected = None
        if selected is None:
            reason = (
                "Emergency stop overrides all adaptive preferences."
                if emergency
                else "Clarification is required because eligible targets remain ambiguous."
                if clarification
                else "No backend passed deterministic safety filtering."
            )
        else:
            snapshot = snapshots[selected]
            verified_successes = snapshot["verification_passes"]
            if advisory_used:
                reason = (
                    f"Selected {selected} after deterministic safety filtering; deterministic "
                    f"score {deterministic_scores[selected]:.2f}, advisory score "
                    f"{advisory_scores.get(selected, 0.5):.2f}, combined score "
                    f"{combined_scores[selected]:.2f}. Advisory weight is bounded at {weight:.2f}."
                )
            else:
                reason = (
                    f"Selected {selected} using deterministic profile evidence: reliability "
                    f"{snapshot['reliability']:.2f}, verified successes {verified_successes}, "
                    f"and fragility {snapshot['fragility']:.2f}."
                )
        decision = AdaptiveExecutionDecision(
            workflow_run_id=request.workflow_run_id,
            workflow_step_id=request.workflow_step_id,
            application_profile_id=profile.profile_id,
            abstract_action=request.abstract_action,
            target_signature=request.target_signature,
            eligible_backends=[candidate.backend for candidate in ranked],
            rejected_backends=rejected,
            selected_backend=selected,
            reliability_snapshot=snapshots,
            deterministic_scores=deterministic_scores,
            advisory_scores=advisory_scores,
            combined_scores=combined_scores,
            advisory_policy=advisory_policy,
            safety_filters_applied=filters,
            policy_version=request.policy_version,
            decision_reason=reason,
            clarification_required=clarification,
        )
        return self.repository.save_adaptive_decision(decision)

    def record_outcome(
        self,
        decision_id: str,
        *,
        execution_succeeded: bool,
        verification_passed: bool,
        failure_class: str | None = None,
    ) -> AdaptiveExecutionDecision:
        decision = self.decision(decision_id)
        if decision.selected_backend is None:
            updated = decision.model_copy(
                update={
                    "execution_outcome": "not_executed",
                    "verification_outcome": "not_run",
                }
            )
            saved = self.repository.save_adaptive_decision(updated)
            self._save_training_experience(saved)
            return saved
        outcome = (
            ProfileOutcome.VERIFIED
            if execution_succeeded and verification_passed
            else ProfileOutcome.SUCCEEDED
            if execution_succeeded
            else ProfileOutcome.FAILED
        )
        self.profiles.record_backend_outcome(
            BackendOutcomeRequest(
                profile_id=decision.application_profile_id,
                abstract_action=decision.abstract_action,
                backend=decision.selected_backend,
                target_type=self._target_type(decision.target_signature),
                verification_method="independent.workflow_verifier",
                outcome=outcome,
                succeeded=execution_succeeded,
                verification_passed=verification_passed,
                fragility=0.5
                if failure_class in {"target_not_found", "stale_automation_id"}
                else 0.0,
                provenance={
                    "adaptive_decision_id": decision.decision_id,
                    "failure_class": failure_class or "none",
                },
            ),
            idempotency_key=f"adaptive-outcome-{decision.decision_id}",
        )
        experience = next(
            (
                item
                for item in reversed(self.profiles.experiences(decision.application_profile_id))
                if item.provenance.get("adaptive_decision_id") == decision.decision_id
            ),
            None,
        )
        updated = decision.model_copy(
            update={
                "execution_outcome": "succeeded" if execution_succeeded else "failed",
                "verification_outcome": "passed" if verification_passed else "failed",
                "reward_signal_id": experience.experience_id if experience else None,
            }
        )
        saved = self.repository.save_adaptive_decision(updated)
        self._save_training_experience(saved)
        return saved

    def _save_training_experience(self, decision: AdaptiveExecutionDecision) -> None:
        self.repository.save_training_experience(
            training_experience_from_adaptive_decision(decision)
        )

    def policy_status(self) -> dict[str, object]:
        status = self.policy_runtime.status().as_dict()
        settings = self.repository.get_settings()
        status["automatic_promotion_enabled"] = settings.automatic_promotion_enabled
        status["automatic_retraining_enabled"] = False
        status["active_policy_version_id"] = settings.active_policy_version_id
        status["policy_version"] = "active-advisory-backend-ranking-v1"
        return status

    def decision(self, decision_id: str) -> AdaptiveExecutionDecision:
        return self.repository.get_adaptive_decision(decision_id)

    def decisions(self) -> list[AdaptiveExecutionDecision]:
        return self.repository.list_adaptive_decisions()

    def explain(self, workflow_run_id: str) -> list[AdaptiveExecutionDecision]:
        return self.repository.list_adaptive_decisions(workflow_run_id=workflow_run_id)

    @staticmethod
    def _target_type(target_signature: str) -> str:
        return target_signature.split(":", maxsplit=1)[0]

    @staticmethod
    def _snapshot(
        candidate: AdaptiveBackendCandidate,
        record: BackendReliabilityRecord | None,
        profile: ApplicationInteractionProfile,
        target_signature: str,
    ) -> dict[str, float | int | bool]:
        attempts = record.attempts if record else 0
        failures = record.failures if record else 0
        reliability = record.reliability if record else 0.0
        fragility = max(candidate.fragility, record.fragility if record else 0.0)
        stable_match = (
            target_signature.removeprefix("automation_id:") in profile.stable_automation_ids
        )
        score = (
            (0.55 * reliability)
            + (0.12 * min(record.verification_passes if record else 0, 20) / 20)
            + (0.10 if stable_match else 0.0)
            + (0.08 if candidate.verification_available else 0.0)
            + (0.06 * (1.0 - candidate.consequence_risk))
            + (0.05 * (1.0 - fragility))
            - (0.10 * (failures / attempts) if attempts else 0.0)
        )
        return {
            "score": score,
            "reliability": reliability,
            "attempts": attempts,
            "verification_passes": record.verification_passes if record else 0,
            "failure_rate": failures / attempts if attempts else 0.0,
            "fragility": fragility,
            "stable_control_match": stable_match,
        }

    @classmethod
    def _rank_key(
        cls,
        candidate: AdaptiveBackendCandidate,
        record: BackendReliabilityRecord | None,
        profile: ApplicationInteractionProfile,
        target_signature: str,
    ) -> tuple[float, int, str]:
        snapshot = cls._snapshot(candidate, record, profile, target_signature)
        hierarchy = {backend: -index for index, backend in enumerate(INTERACTION_BACKEND_HIERARCHY)}
        return (
            float(snapshot["score"]),
            hierarchy.get(candidate.backend, -len(hierarchy)),
            candidate.backend,
        )

    @staticmethod
    def _clarification_required(
        ranked: list[AdaptiveBackendCandidate],
        snapshots: dict[str, dict[str, float | int | bool]],
        profile: ApplicationInteractionProfile,
        target_signature: str,
    ) -> bool:
        stable = target_signature.removeprefix("automation_id:") in profile.stable_automation_ids
        if stable or len(ranked) < 2:
            return False
        first = float(snapshots[ranked[0].backend]["score"])
        second = float(snapshots[ranked[1].backend]["score"])
        return abs(first - second) < 0.02


__all__ = [
    "AdaptiveBackendCandidate",
    "AdaptiveExecutionDecision",
    "AdaptiveExecutionRequest",
    "AdaptiveExecutionService",
]
