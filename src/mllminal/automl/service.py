"""Rank bounded local policy candidates using explicit safety constraints."""

from mllminal.automl.contracts import (
    AutoMLCandidate,
    AutoMLRequest,
    AutoMLResult,
)


class LocalAutoMLService:
    def rank(self, request: AutoMLRequest) -> AutoMLResult:
        candidates = [
            AutoMLCandidate(
                candidate_name=metric.candidate_name,
                parameters=metric.parameters,
                mean_reward=metric.mean_reward,
                safe_action_rate=metric.safe_action_rate,
                invalid_action_rate=metric.invalid_action_rate,
                sample_count=metric.sample_count,
                eligible_for_review=(
                    metric.safe_action_rate >= request.minimum_safe_action_rate
                    and metric.invalid_action_rate <= request.maximum_invalid_action_rate
                ),
            )
            for metric in request.metrics
        ]
        candidates.sort(
            key=lambda candidate: (
                not candidate.eligible_for_review,
                -candidate.mean_reward,
                -candidate.safe_action_rate,
                candidate.invalid_action_rate,
            )
        )
        candidates = candidates[: request.max_candidates]
        selected = next(
            (candidate.id for candidate in candidates if candidate.eligible_for_review), None
        )
        return AutoMLResult(candidates=candidates, selected_candidate_id=selected)
