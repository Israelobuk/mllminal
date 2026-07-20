"""Turn mined repetitions into bounded suggestions, never automatic actions."""

from mllminal.assistance.contracts import (
    AssistanceRequest,
    AssistanceResult,
    AssistanceSuggestion,
)
from mllminal.mining.contracts import MiningResult, WorkflowCandidate


class ProactiveAssistanceService:
    def suggest(self, result: MiningResult, request: AssistanceRequest) -> AssistanceResult:
        candidates = [
            candidate
            for candidate in result.candidates
            if candidate.confidence >= request.minimum_confidence
        ][: request.max_suggestions]
        return AssistanceResult(
            source_event_count=result.event_count,
            suggestions=[self._suggestion(candidate) for candidate in candidates],
        )

    @staticmethod
    def _suggestion(candidate: WorkflowCandidate) -> AssistanceSuggestion:
        steps = " then ".join(step.kind for step in candidate.steps)
        return AssistanceSuggestion(
            workflow_candidate_id=candidate.id,
            title=f"Repeat workflow in {candidate.application}",
            application=candidate.application,
            summary=f"Observed {candidate.occurrences} repetitions: {steps}",
            occurrences=candidate.occurrences,
            confidence=candidate.confidence,
        )
