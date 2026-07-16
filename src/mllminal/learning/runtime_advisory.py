"""Safe, advisory-only bridge between the runtime and offline learning state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mllminal.learning.contracts import (
    ExperienceOutcome,
    ExperienceRecord,
    ExperienceStatus,
    PolicyAction,
    PolicyCheckpoint,
    PolicyDecision,
)
from mllminal.learning.features import build_action_mask, encode_features
from mllminal.learning.governance import CandidateGovernanceService
from mllminal.learning.policy import ActionPolicy
from mllminal.learning.registry import PolicyRegistry
from mllminal.learning.replay import LearningRepository
from mllminal.learning.rewards import calculate_reward, is_eligible_experience


@dataclass(frozen=True)
class AdvisoryRecommendation:
    decision: PolicyDecision
    final_action: PolicyAction
    fallback_reason: str | None


class LearningRuntimeAdvisor:
    def __init__(self, repository: LearningRepository, checkpoint_root: Path) -> None:
        self.repository = repository
        self.governance = CandidateGovernanceService(
            repository, PolicyRegistry(repository, checkpoint_root)
        )

    def recommend(self, task_id: str) -> AdvisoryRecommendation | None:
        settings = self.repository.get_settings()
        if not settings.enabled:
            return None
        active = self.repository.get_promoted_policy()
        policy: ActionPolicy = self.governance.load_active_or_fallback(active)
        mask = build_action_mask(PolicyCheckpoint.PLAN_READY)
        features = encode_features(
            task_state_index=2,
            provider="none",
            message_length=0,
            conversation_count=0,
            workspace_attached=True,
            available_tool_count=1,
            pending_approval_count=0,
            prior_tool_succeeded=None,
            prior_verification_succeeded=None,
            retry_count=0,
            correction_count=0,
            task_age_seconds=0.0,
            provider_failure=False,
            plan_ready=True,
            verified_result=False,
        )
        recommendation = policy.recommend(
            features, tuple(mask), confidence_threshold=settings.confidence_threshold
        )
        decision = PolicyDecision(
            task_id=task_id,
            selected_action=recommendation.action,
            confidence=recommendation.confidence,
            policy_version_id=active.id,
            scores=recommendation.scores,
            used_safe_fallback=recommendation.used_safe_fallback,
        )
        self.repository.save_decision(
            decision, decision_sequence=self.repository.count_decisions() + 1
        )
        payload = {
            "decision_id": decision.id,
            "policy_version_id": active.id,
            "final_runtime_action": PolicyAction.REQUEST_APPROVAL.value,
            "fallback_reason": recommendation.fallback_reason or "",
        }
        self.repository.append_event("learning.policy.recommended", payload)
        if recommendation.used_safe_fallback:
            self.repository.append_event("learning.policy.fallback", payload)
        return AdvisoryRecommendation(
            decision, PolicyAction.REQUEST_APPROVAL, recommendation.fallback_reason
        )

    def finalize(
        self, task_id: str, *, verified: bool, completed: bool, corrected: bool = False
    ) -> ExperienceRecord | None:
        settings = self.repository.get_settings()
        if not settings.enabled:
            return None
        decisions = self.repository.list_decisions(task_id)
        if not decisions:
            return None
        decision = decisions[-1]
        outcome = ExperienceOutcome(
            terminal=verified or completed,
            task_completed=completed and verified,
            verification_passed=verified,
            tool_succeeded=verified,
            user_corrected=corrected,
            task_failed=not verified and completed,
        )
        reward = calculate_reward(outcome)
        record = ExperienceRecord(
            task_id=task_id,
            decision_id=decision.id,
            idempotency_key=f"runtime:{task_id}:{decision.id}",
            selected_action=decision.selected_action,
            outcome=outcome,
            reward=reward,
            status=ExperienceStatus.ELIGIBLE
            if is_eligible_experience(
                ExperienceRecord(
                    task_id=task_id,
                    decision_id=decision.id,
                    idempotency_key=f"runtime:{task_id}:{decision.id}",
                    selected_action=decision.selected_action,
                    outcome=outcome,
                    reward=reward,
                )
            )
            else ExperienceStatus.EXCLUDED,
        )
        saved, created = self.repository.save_experience(
            record, decision_sequence=self.repository.count_decisions()
        )
        if created and saved.status is ExperienceStatus.ELIGIBLE:
            self.repository.add_replay_entry(
                saved.id,
                features=(0.0,) * 15,
                action=saved.selected_action or PolicyAction.STOP_SAFELY,
                reward=saved.reward.total if saved.reward else 0.0,
            )
            self.repository.append_event(
                "learning.experience.recorded", {"experience_id": saved.id}
            )
        elif created:
            self.repository.append_event(
                "learning.experience.rejected", {"experience_id": saved.id}
            )
        return saved
