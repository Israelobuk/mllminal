from mllminal.learning.contracts import PolicyDomain, TrainingExperience


def test_training_experience_keeps_domain_reward_and_privacy_provenance() -> None:
    experience = TrainingExperience(
        policy_domain=PolicyDomain.SUGGESTION_RANKING,
        source_record_type="suggestion_feedback",
        source_record_id="suggestion-1",
        context_features={"occurrence_count": 6.0, "rejection_rate": 0.0},
        candidate_actions=("present", "defer"),
        selected_action="present",
        baseline_score=0.7,
        policy_score=None,
        execution_outcome="not_applicable",
        verification_outcome="not_applicable",
        user_feedback="accepted",
        reward=1.0,
        reward_components={"accepted": 1.0},
        reward_formula_version="rewards_v2",
        privacy_approved=True,
        eligible_for_training=True,
    )

    assert experience.policy_domain is PolicyDomain.SUGGESTION_RANKING
    assert experience.privacy_approved is True
    assert experience.reward_components == {"accepted": 1.0}
