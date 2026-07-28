"""Privacy-minimized collectors for durable offline policy evidence."""

from __future__ import annotations

from mllminal.assistance.contracts import SuggestionFeedback, SuggestionFeedbackKind
from mllminal.learning.adaptive_contracts import AdaptiveExecutionDecision
from mllminal.learning.contracts import PolicyDomain, TrainingExperience


def training_experience_from_suggestion_feedback(
    feedback: SuggestionFeedback,
) -> TrainingExperience:
    """Convert feedback kind and opaque IDs into allowlisted suggestion evidence."""

    accepted = feedback.kind is SuggestionFeedbackKind.ACCEPT
    reward = 1.0 if accepted else -1.0
    context_features = {"prior_acceptance_rate": 1.0} if accepted else {"rejection_rate": 1.0}
    return TrainingExperience(
        policy_domain=PolicyDomain.SUGGESTION_RANKING,
        source_record_type="suggestion_feedback",
        source_record_id=feedback.feedback_id,
        context_features=context_features,
        candidate_actions=("present", "defer"),
        selected_action="present" if accepted else "defer",
        baseline_score=0.5,
        user_feedback=feedback.kind.value,
        reward=reward,
        reward_components={"feedback": reward},
        privacy_approved=True,
        eligible_for_training=True,
        feature_schema_version="training_features_v1",
        created_at=feedback.created_at,
    )


def training_experience_from_adaptive_decision(
    decision: AdaptiveExecutionDecision,
) -> TrainingExperience:
    """Convert one backend decision outcome into allowlisted numeric evidence."""

    candidate_actions = tuple(
        dict.fromkeys(
            [*decision.eligible_backends, *(item.backend for item in decision.rejected_backends)]
        )
    )
    selected_snapshot = (
        decision.reliability_snapshot.get(decision.selected_backend, {})
        if decision.selected_backend is not None
        else {}
    )
    execution = decision.execution_outcome
    verification = decision.verification_outcome
    reward = (
        1.0
        if execution == "succeeded" and verification == "passed"
        else 0.25
        if execution == "succeeded"
        else -1.0
        if execution == "failed"
        else 0.0
    )
    emergency = "emergency_stop" in decision.safety_filters_applied
    eligible = (
        decision.selected_backend is not None
        and not emergency
        and not decision.clarification_required
        and execution is not None
    )
    context_features = {
        "candidate_count": float(len(candidate_actions)),
        "eligible_count": float(len(decision.eligible_backends)),
        "clarification_required": float(decision.clarification_required),
        "emergency_stop": float(emergency),
        "selected_reliability": float(selected_snapshot.get("reliability", 0.0)),
        "selected_fragility": float(selected_snapshot.get("fragility", 0.0)),
    }
    return TrainingExperience(
        policy_domain=PolicyDomain.BACKEND_RANKING,
        source_record_type="adaptive_execution",
        source_record_id=decision.decision_id,
        context_features=context_features,
        candidate_actions=candidate_actions or ("STOP_SAFELY",),
        selected_action=decision.selected_backend,
        baseline_score=float(selected_snapshot.get("score", 0.0))
        if decision.selected_backend is not None
        else None,
        execution_outcome=execution,
        verification_outcome=verification,
        reward=reward,
        reward_components={"execution": reward},
        privacy_approved=True,
        eligible_for_training=eligible,
    )
