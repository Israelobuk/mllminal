from mllminal.learning.contracts import PolicyDomain, TrainingExperience
from mllminal.learning.offline_splits import split_training_experiences


def _experience(source_id: str, action: str) -> TrainingExperience:
    return TrainingExperience(
        policy_domain=PolicyDomain.SUGGESTION_RANKING,
        source_record_type="workflow_episode",
        source_record_id=source_id,
        context_features={"occurrence_count": 0.5},
        candidate_actions=("present", "defer"),
        selected_action=action,
        baseline_score=0.5,
        reward=1.0,
        reward_components={"accepted": 1.0},
        privacy_approved=True,
        eligible_for_training=True,
    )


def test_deterministic_split_keeps_source_episodes_in_one_partition() -> None:
    experiences = [
        _experience("episode-a", "present"),
        _experience("episode-a", "defer"),
        _experience("episode-b", "present"),
        _experience("episode-c", "defer"),
        _experience("episode-d", "present"),
        _experience("episode-e", "defer"),
    ]

    first = split_training_experiences(experiences, seed=7)
    second = split_training_experiences(experiences, seed=7)
    partitions = {
        source_id: {
            partition
            for partition, rows in (
                ("train", first.train),
                ("validation", first.validation),
                ("test", first.test),
            )
            for experience in rows
            if experience.source_record_id == source_id
        }
        for source_id in {experience.source_record_id for experience in experiences}
    }

    assert first == second
    assert first.strategy == "source-record-grouped-v1"
    assert all(len(source_partitions) == 1 for source_partitions in partitions.values())
    assert sum(len(rows) for rows in (first.train, first.validation, first.test)) == len(
        experiences
    )
    assert len(first.train) > 0
    assert len(first.validation) > 0
    assert len(first.test) > 0
