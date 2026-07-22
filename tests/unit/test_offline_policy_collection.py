from mllminal.assistance.contracts import SuggestionFeedback, SuggestionFeedbackKind
from mllminal.learning.contracts import PolicyDomain
from mllminal.learning.offline_collection import training_experience_from_suggestion_feedback


def test_suggestion_feedback_becomes_minimized_training_evidence() -> None:
    feedback = SuggestionFeedback(
        suggestion_id="suggestion-1",
        candidate_id="candidate-1",
        kind=SuggestionFeedbackKind.ACCEPT,
        idempotency_key="feedback-1",
    )

    experience = training_experience_from_suggestion_feedback(feedback)

    assert experience.policy_domain is PolicyDomain.SUGGESTION_RANKING
    assert experience.source_record_type == "suggestion_feedback"
    assert experience.source_record_id == feedback.feedback_id
    assert experience.selected_action == "present"
    assert experience.reward == 1.0
    assert experience.context_features == {"prior_acceptance_rate": 1.0}
    assert experience.privacy_approved is True
    assert experience.eligible_for_training is True
    assert "idempotency_key" not in experience.model_dump()
