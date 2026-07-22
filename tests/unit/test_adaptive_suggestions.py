from mllminal.assistance.adaptive import AdaptiveSuggestionService
from mllminal.assistance.contracts import (
    PreferenceScope,
    SuggestionFeedbackKind,
    UserWorkflowPreference,
)
from mllminal.contracts import utc_now
from mllminal.learning.replay import LearningRepository
from mllminal.mining.contracts import MinedStep, WorkflowCandidate


def _candidate() -> WorkflowCandidate:
    now = utc_now()
    return WorkflowCandidate(
        id="candidate-1",
        application="explorer",
        steps=[
            MinedStep(application="explorer", kind="control.invoked"),
            MinedStep(application="explorer", kind="control.invoked"),
        ],
        occurrences=6,
        confidence=0.9,
        first_seen=now,
        last_seen=now,
        source_event_ids=["event-1", "event-2"],
    )


def test_ranked_suggestion_is_durable_and_rejection_lowers_its_next_score(tmp_path) -> None:
    database = tmp_path / "learning.db"
    repository = LearningRepository(database)
    repository.initialize()
    service = AdaptiveSuggestionService(repository)

    first = service.propose(_candidate(), verification_available=True)
    assert first.status.value == "eligible"
    assert first.ranking_components["occurrence_frequency"] > 0
    assert service.suggestion(first.suggestion_id).suggestion_id == first.suggestion_id

    service.feedback(first.suggestion_id, SuggestionFeedbackKind.REJECT, idempotency_key="reject-1")
    assert service.suggestion(first.suggestion_id).status.value == "rejected"
    second = service.propose(
        _candidate().model_copy(
            update={"occurrences": 7, "source_event_ids": ["event-1", "event-3"]}
        ),
        verification_available=True,
    )

    assert second.ranking_score < first.ranking_score
    assert second.prior_rejection_count == 1


def test_workflow_preference_overrides_application_and_global_preferences(tmp_path) -> None:
    repository = LearningRepository(tmp_path / "learning.db")
    repository.initialize()
    service = AdaptiveSuggestionService(repository)
    candidate = _candidate()
    service.set_preference(UserWorkflowPreference(scope=PreferenceScope.GLOBAL, enabled=False))
    service.set_preference(
        UserWorkflowPreference(
            scope=PreferenceScope.APPLICATION,
            application=candidate.application,
            enabled=True,
        )
    )
    service.set_preference(
        UserWorkflowPreference(
            scope=PreferenceScope.WORKFLOW,
            candidate_id=candidate.id,
            enabled=False,
        )
    )

    suggestion = service.propose(candidate, verification_available=True)

    assert service.preference_for(candidate).scope is PreferenceScope.WORKFLOW
    assert suggestion.status.value == "pending"
    assert "disabled_by_preference" in suggestion.eligibility_reasons


def test_emergency_stop_and_missing_verification_keep_suggestions_advisory(tmp_path) -> None:
    repository = LearningRepository(tmp_path / "learning.db")
    repository.initialize()
    service = AdaptiveSuggestionService(repository, emergency_stop_active=lambda: True)

    suggestion = service.propose(_candidate(), verification_available=False)

    assert suggestion.status.value == "pending"
    assert suggestion.permission_preserved is True
    assert suggestion.approval_preserved is True
    assert {"emergency_stop_active", "independent_verification_required"} <= set(
        suggestion.eligibility_reasons
    )
