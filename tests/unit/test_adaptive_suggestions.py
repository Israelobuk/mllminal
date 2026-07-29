from mllminal.assistance.adaptive import AdaptiveSuggestionService
from mllminal.assistance.contracts import (
    PreferenceScope,
    SuggestionFeedbackKind,
    UserWorkflowPreference,
)
from mllminal.assistance.suggestion_runtime import SuggestionAdvisoryResult
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


class _AdvisoryRuntime:
    advisory_weight = 0.2

    def evaluate(self, *_args, **_kwargs) -> SuggestionAdvisoryResult:
        return SuggestionAdvisoryResult(
            score=0.95,
            provenance={"active": True, "policy_domain": "SUGGESTION_RANKING"},
        )


def test_active_suggestion_policy_adjusts_score_without_changing_eligibility(tmp_path) -> None:
    repository = LearningRepository(tmp_path / "learning.db")
    repository.initialize()
    service = AdaptiveSuggestionService(repository, policy_runtime=_AdvisoryRuntime())

    suggestion = service.propose(_candidate(), verification_available=True)

    assert suggestion.status.value == "eligible"
    assert suggestion.deterministic_ranking_score is not None
    assert suggestion.advisory_score == 0.95
    assert suggestion.combined_ranking_score == suggestion.ranking_score
    assert suggestion.ranking_score > suggestion.deterministic_ranking_score
    assert suggestion.advisory_policy["active"] is True
    assert suggestion.advisory_policy["used_in_ranking"] is True


def test_active_suggestion_policy_cannot_make_unverified_candidate_eligible(tmp_path) -> None:
    repository = LearningRepository(tmp_path / "learning.db")
    repository.initialize()
    service = AdaptiveSuggestionService(repository, policy_runtime=_AdvisoryRuntime())

    suggestion = service.propose(_candidate(), verification_available=False)

    assert suggestion.status.value == "pending"
    assert suggestion.advisory_score is None
    assert "independent_verification_required" in suggestion.eligibility_reasons
