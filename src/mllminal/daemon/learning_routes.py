"""Additional authenticated projections for the learning CLI."""

from __future__ import annotations

import secrets
from typing import Annotated, Any, cast

from fastapi import Depends, FastAPI, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from mllminal.contracts import ErrorEnvelope
from mllminal.learning.contracts import PolicyDomain
from mllminal.learning.evaluation import EvaluationCase
from mllminal.learning.governance import CandidateGovernanceService, PromotionApprovalError
from mllminal.learning.offline_jobs import OfflineTrainingJobManager
from mllminal.learning.offline_service import OfflinePolicyDataService
from mllminal.learning.registry import PolicyRegistry


class ReplaySnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_domain: PolicyDomain
    seed: int = 42


class PromotionApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")

    explicitly_approved: bool = True


def register_learning_routes(app: FastAPI, settings: Any, token: str) -> None:
    repository = app.state.learning_repository
    jobs = OfflineTrainingJobManager(repository, settings.data_dir / "learning" / "offline")
    app.state.offline_jobs = jobs

    async def authorize(authorization: Annotated[str | None, Header()] = None) -> None:
        expected = f"Bearer {token}"
        if authorization is None or not secrets.compare_digest(authorization, expected):
            raise PermissionError("Valid bearer token required")

    def error(code: str, message: str, status_code: int) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content=ErrorEnvelope(code=code, message=message).model_dump(mode="json"),
        )

    def governance() -> CandidateGovernanceService:
        return CandidateGovernanceService(
            repository,
            PolicyRegistry(repository, settings.data_dir / "learning" / "checkpoints"),
        )

    @app.get("/v1/learning/experiences/{experience_id}", dependencies=[Depends(authorize)])
    async def learning_experience(experience_id: str) -> dict[str, Any]:
        for item in repository.list_profile_experiences():
            if item.experience_id == experience_id:
                return cast(dict[str, Any], item.model_dump(mode="json"))
        raise KeyError(experience_id)

    @app.post("/v1/learning/replay/snapshots", dependencies=[Depends(authorize)])
    async def create_replay_snapshot(
        body: ReplaySnapshotRequest,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        snapshot = OfflinePolicyDataService(
            repository, settings.data_dir / "learning" / "offline"
        ).snapshot(body.policy_domain, seed=body.seed)
        return snapshot.model_dump(mode="json")

    @app.get("/v1/learning/replay/snapshots", dependencies=[Depends(authorize)])
    async def list_replay_snapshots() -> list[dict[str, Any]]:
        return [
            cast(dict[str, Any], snapshot.model_dump(mode="json"))
            for snapshot in repository.list_replay_snapshots()
        ]

    @app.get("/v1/learning/replay/snapshots/{snapshot_id}", dependencies=[Depends(authorize)])
    async def get_replay_snapshot(snapshot_id: str) -> dict[str, Any]:
        return cast(
            dict[str, Any], repository.get_replay_snapshot(snapshot_id).model_dump(mode="json")
        )

    @app.get("/v1/learning/policies/{policy_id}", dependencies=[Depends(authorize)])
    async def get_policy(policy_id: str) -> dict[str, Any]:
        return cast(
            dict[str, Any], repository.get_policy_version(policy_id).model_dump(mode="json")
        )

    @app.post("/v1/learning/policies/{candidate_id}/evaluate", dependencies=[Depends(authorize)])
    async def evaluate_policy(
        candidate_id: str, idempotency_key: Annotated[str, Header(alias="Idempotency-Key")]
    ) -> Any:
        candidate = repository.get_policy_version(candidate_id)
        if candidate.training_run_id is None:
            return error("invalid_policy", "Candidate policy cannot be evaluated", 422)
        samples = repository.sample_replay(
            repository.count_replay_entries(), seed=repository.get_settings().seed
        )
        if not samples:
            return error("no_replay_samples", "No held-out replay samples available", 409)
        result = governance().evaluate(
            candidate.id,
            candidate.training_run_id,
            [EvaluationCase(sample=sample, action_mask=(True,) * 9) for sample in samples],
        )
        return result.report.model_dump(mode="json")

    @app.get("/v1/learning/policies/{candidate_id}/compare", dependencies=[Depends(authorize)])
    async def compare_policy(candidate_id: str) -> dict[str, Any]:
        candidate = repository.get_policy_version(candidate_id)
        active = repository.get_promoted_policy()
        return {
            "candidate_policy_id": candidate.id,
            "candidate_lifecycle": candidate.lifecycle.value,
            "active_policy_id": active.id,
            "active_policy_name": active.name,
        }

    @app.post("/v1/learning/policies/{candidate_id}/promote", dependencies=[Depends(authorize)])
    async def promote_policy(
        candidate_id: str,
        body: PromotionApproval,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> Any:
        reports = [
            report
            for report in repository.list_evaluation_reports()
            if report.candidate_policy_id == candidate_id
        ]
        if not reports:
            return error("missing_evaluation", "Candidate has no evaluation report", 409)
        try:
            policy = governance().promote(
                candidate_id,
                reports[-1].id,
                explicitly_approved=body.explicitly_approved,
                idempotency_key=idempotency_key,
            )
        except PromotionApprovalError as exception:
            return error("promotion_rejected", str(exception), 409)
        return policy.model_dump(mode="json")

    @app.post("/v1/learning/policies/{policy_id}/rollback", dependencies=[Depends(authorize)])
    async def rollback_policy(
        policy_id: str,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> Any:
        record = repository.rollback_policy(
            policy_id, reason="CLI operator rollback", idempotency_key=idempotency_key
        )[0]
        return record.model_dump(mode="json")

    @app.get("/v1/learning/active", dependencies=[Depends(authorize)])
    async def active_policy(domain: PolicyDomain) -> dict[str, Any]:
        active = repository.get_promoted_policy()
        if active.policy_domain is not None and active.policy_domain is not domain:
            return {"policy_domain": domain.value, "lifecycle": "INACTIVE"}
        return cast(dict[str, Any], active.model_dump(mode="json"))

    @app.get("/v1/learning/workers/{job_id}", dependencies=[Depends(authorize)])
    async def worker_status(job_id: str) -> dict[str, Any]:
        return jobs.status(job_id).model_dump(mode="json")

    @app.post("/v1/learning/workers/{job_id}/cancel", dependencies=[Depends(authorize)])
    async def worker_cancel(
        job_id: str,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict[str, Any]:
        return jobs.cancel(job_id).model_dump(mode="json")
