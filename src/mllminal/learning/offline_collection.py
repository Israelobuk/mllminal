"""Privacy-minimized collectors for durable offline policy evidence."""

from __future__ import annotations

from mllminal.assistance.contracts import SuggestionFeedback, SuggestionFeedbackKind
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
