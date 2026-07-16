from pathlib import Path

from mllminal.learning.contracts import PolicyAction
from mllminal.learning.replay import LearningRepository
from mllminal.learning.runtime_advisory import LearningRuntimeAdvisor


def test_disabled_learning_preserves_no_advisory_or_experience(tmp_path: Path) -> None:
    repository = LearningRepository(tmp_path / "state.db")
    repository.initialize()
    repository.update_settings(enabled=False)
    advisor = LearningRuntimeAdvisor(repository, tmp_path / "checkpoints")

    assert advisor.recommend("task-1") is None
    assert advisor.finalize("task-1", verified=True, completed=True) is None
    assert repository.count_decisions() == 0
    assert repository.count_experiences() == 0


def test_advisory_is_masked_persisted_and_verified_completion_enters_replay(tmp_path: Path) -> None:
    repository = LearningRepository(tmp_path / "state.db")
    repository.initialize()
    advisor = LearningRuntimeAdvisor(repository, tmp_path / "checkpoints")

    recommendation = advisor.recommend("task-1")
    experience = advisor.finalize("task-1", verified=True, completed=True)

    assert recommendation is not None
    assert recommendation.final_action is PolicyAction.REQUEST_APPROVAL
    assert experience is not None
    assert experience.status.value == "ELIGIBLE"
    assert repository.count_replay_entries() == 1
    assert {event.event_type for event in repository.list_events()} >= {
        "learning.policy.recommended",
        "learning.experience.recorded",
    }
