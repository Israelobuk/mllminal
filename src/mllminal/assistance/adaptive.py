"""Durable, deterministic, and advisory workflow suggestions."""

import hashlib
import json
from collections.abc import Callable

from mllminal.assistance.contracts import (
    AdaptiveWorkflowSuggestion,
    PreferenceScope,
    SuggestionFeedback,
    SuggestionFeedbackKind,
    SuggestionRankingDecision,
    SuggestionStatus,
    UserWorkflowPreference,
    WorkflowAdaptationProposal,
)
from mllminal.contracts import utc_now
from mllminal.learning.replay import LearningRepository
from mllminal.mining.contracts import WorkflowCandidate


class AdaptiveSuggestionService:
    """Ranks candidates deterministically; it never grants access or executes work."""

    def __init__(
        self,
        repository: LearningRepository,
        *,
        emergency_stop_active: Callable[[], bool] = lambda: False,
    ) -> None:
        self.repository = repository
        self.emergency_stop_active = emergency_stop_active

    def propose(
        self, candidate: WorkflowCandidate, *, verification_available: bool
    ) -> AdaptiveWorkflowSuggestion:
        evidence_key = self._evidence_key(candidate)
        preference = self.preference_for(candidate)
        rejections = self.repository.count_suggestion_feedback(
            candidate.id, SuggestionFeedbackKind.REJECT.value
        )
        components = {
            "occurrence_frequency": min(candidate.occurrences / 10, 1.0),
            "confidence": candidate.confidence,
            "verification_availability": 0.5 if verification_available else -1.0,
            "preference": 0.3
            if preference and preference.enabled
            else (-1.0 if preference else 0.0),
            "rejection_penalty": -min(rejections * 0.15, 0.6),
        }
        stopped = self.emergency_stop_active()
        eligible = (
            verification_available
            and candidate.confidence >= 0.5
            and not stopped
            and (preference is None or preference.enabled)
        )
        reasons: list[str] = []
        if not verification_available:
            reasons.append("independent_verification_required")
        if stopped:
            reasons.append("emergency_stop_active")
        if preference is not None and not preference.enabled:
            reasons.append("disabled_by_preference")
        suggestion = AdaptiveWorkflowSuggestion(
            candidate_id=candidate.id,
            application=candidate.application,
            title=f"Create draft workflow in {candidate.application}",
            summary=f"Observed {candidate.occurrences} repeated semantic steps.",
            source_episode_ids=candidate.source_event_ids,
            occurrence_count=candidate.occurrences,
            confidence=candidate.confidence,
            verification_availability=verification_available,
            emergency_stop_active=stopped,
            prior_rejection_count=rejections,
            ranking_score=round(sum(components.values()) / len(components), 6),
            ranking_components=components,
            ranking_explanation=self._explanation(candidate, preference, rejections),
            eligibility_reasons=reasons,
            status=SuggestionStatus.ELIGIBLE if eligible else SuggestionStatus.PENDING,
        )
        saved, created = self.repository.save_adaptive_suggestion(
            suggestion, evidence_key=evidence_key
        )
        if created:
            self.repository.save_suggestion_ranking(
                SuggestionRankingDecision(
                    suggestion_id=saved.suggestion_id,
                    candidate_id=saved.candidate_id,
                    ranking_score=saved.ranking_score,
                    ranking_components=saved.ranking_components,
                    explanation=saved.ranking_explanation,
                )
            )
        return saved

    def suggestions(self) -> list[AdaptiveWorkflowSuggestion]:
        return self.repository.list_adaptive_suggestions()

    def suggestion(self, suggestion_id: str) -> AdaptiveWorkflowSuggestion:
        return self.repository.get_adaptive_suggestion(suggestion_id)

    def feedback(
        self, suggestion_id: str, kind: SuggestionFeedbackKind, *, idempotency_key: str
    ) -> SuggestionFeedback:
        suggestion = self.suggestion(suggestion_id)
        feedback, created = self.repository.save_suggestion_feedback(
            SuggestionFeedback(
                suggestion_id=suggestion_id,
                candidate_id=suggestion.candidate_id,
                kind=kind,
                idempotency_key=idempotency_key,
            )
        )
        if created:
            self.repository.update_adaptive_suggestion(
                suggestion.model_copy(
                    update={"status": self._feedback_status(kind), "updated_at": utc_now()}
                )
            )
        return feedback

    def set_preference(self, preference: UserWorkflowPreference) -> UserWorkflowPreference:
        self._validate_preference(preference)
        return self.repository.save_workflow_preference(preference)

    def preferences(self) -> list[UserWorkflowPreference]:
        return self.repository.list_workflow_preferences()

    def preference_for(self, candidate: WorkflowCandidate) -> UserWorkflowPreference | None:
        preferences = self.preferences()
        for scope, predicate in (
            (PreferenceScope.WORKFLOW, lambda item: item.candidate_id == candidate.id),
            (PreferenceScope.APPLICATION, lambda item: item.application == candidate.application),
            (PreferenceScope.GLOBAL, lambda item: True),
        ):
            matches = [item for item in preferences if item.scope is scope and predicate(item)]
            if matches:
                return max(matches, key=lambda item: item.updated_at)
        return None

    def propose_adaptation(self, suggestion_id: str) -> WorkflowAdaptationProposal:
        suggestion = self.suggestion(suggestion_id)
        return self.repository.save_adaptation_proposal(
            WorkflowAdaptationProposal(
                candidate_id=suggestion.candidate_id,
                source_suggestion_id=suggestion.suggestion_id,
                change_summary="Draft adaptation based on repeated reviewed workflow evidence.",
                evidence_count=suggestion.occurrence_count,
            )
        )

    @staticmethod
    def _feedback_status(kind: SuggestionFeedbackKind) -> SuggestionStatus:
        return {
            SuggestionFeedbackKind.ACCEPT: SuggestionStatus.ACCEPTED,
            SuggestionFeedbackKind.REJECT: SuggestionStatus.REJECTED,
            SuggestionFeedbackKind.DISMISS: SuggestionStatus.DISMISSED,
            SuggestionFeedbackKind.SNOOZE: SuggestionStatus.SNOOZED,
            SuggestionFeedbackKind.DISABLE: SuggestionStatus.DISABLED,
        }[kind]

    @staticmethod
    def _evidence_key(candidate: WorkflowCandidate) -> str:
        value = json.dumps(
            {
                "candidate_id": candidate.id,
                "occurrences": candidate.occurrences,
                "confidence": candidate.confidence,
                "source_event_ids": candidate.source_event_ids,
            },
            sort_keys=True,
        )
        return hashlib.sha256(value.encode()).hexdigest()

    @staticmethod
    def _validate_preference(preference: UserWorkflowPreference) -> None:
        if preference.scope is PreferenceScope.APPLICATION and preference.application is None:
            raise ValueError("application preferences require an application")
        if preference.scope is PreferenceScope.WORKFLOW and preference.candidate_id is None:
            raise ValueError("workflow preferences require a candidate_id")

    @staticmethod
    def _explanation(
        candidate: WorkflowCandidate,
        preference: UserWorkflowPreference | None,
        rejections: int,
    ) -> list[str]:
        explanation = [
            f"Observed {candidate.occurrences} times.",
            f"Candidate confidence is {candidate.confidence:.2f}.",
            "Independent verification remains required before execution.",
        ]
        if preference is not None:
            explanation.append(f"Applied {preference.scope.value} preference.")
        if rejections:
            explanation.append(f"Applied {rejections} prior rejection penalty.")
        return explanation
