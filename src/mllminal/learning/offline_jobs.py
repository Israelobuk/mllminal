"""Durable local orchestration for asynchronous offline policy training jobs."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from threading import Event, Lock
from typing import Any

from pydantic import Field

from mllminal.contracts import Contract, new_id, utc_now
from mllminal.learning.contracts import PolicyDomain
from mllminal.learning.offline_service import OfflinePolicyTrainingService
from mllminal.learning.offline_training import OfflineTrainingConfig
from mllminal.learning.replay import LearningRepository


class OfflineTrainingJob(Contract):
    """Safe status projection for one asynchronous local training request."""

    job_id: str = Field(default_factory=new_id)
    policy_domain: PolicyDomain
    status: str = "QUEUED"
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    training_run_id: str | None = None
    candidate_policy_id: str | None = None
    worker_status: str | None = None
    failure_reason: str | None = None
    created_at: Any = Field(default_factory=utc_now)
    updated_at: Any = Field(default_factory=utc_now)


@dataclass
class _JobState:
    job: OfflineTrainingJob
    cancel_event: Event
    future: Future[None] | None = None


class OfflineTrainingJobManager:
    """Run at most one local training job at a time and persist safe status events."""

    def __init__(self, repository: LearningRepository, root: Any) -> None:
        self.repository = repository
        self.service = OfflinePolicyTrainingService(repository, root)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mllminal-training")
        self._lock = Lock()
        self._jobs: dict[str, _JobState] = {}

    def submit(
        self,
        policy_domain: PolicyDomain,
        config: OfflineTrainingConfig,
        *,
        timeout_seconds: float,
    ) -> OfflineTrainingJob:
        job = OfflineTrainingJob(policy_domain=policy_domain)
        state = _JobState(job=job, cancel_event=Event())
        with self._lock:
            self._jobs[job.job_id] = state
        self._record("learning.offline_job.created", job)
        state.future = self._executor.submit(self._run, state, config, timeout_seconds)
        return job

    def status(self, job_id: str) -> OfflineTrainingJob:
        state = self._jobs.get(job_id)
        if state is not None:
            self._refresh(state)
            return state.job
        durable = self._load_durable(job_id)
        if durable is None:
            raise KeyError(job_id)
        return durable

    def cancel(self, job_id: str) -> OfflineTrainingJob:
        state = self._jobs.get(job_id)
        if state is None:
            durable = self._load_durable(job_id)
            if durable is None:
                raise KeyError(job_id)
            return durable
        self._refresh(state)
        if state.job.status in {"COMPLETED", "FAILED", "CANCELLED"}:
            return state.job
        state.cancel_event.set()
        self._update(state, status="CANCELLING")
        self._record("learning.offline_job.cancellation_requested", state.job)
        return state.job

    def close(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)

    def _run(
        self,
        state: _JobState,
        config: OfflineTrainingConfig,
        timeout_seconds: float,
    ) -> None:
        self._update(state, status="RUNNING", progress=0.05)
        try:
            result = self.service.train(
                state.job.policy_domain,
                config,
                timeout_seconds=timeout_seconds,
                cancel_requested=state.cancel_event.is_set,
            )
        except Exception as error:
            self._update(state, status="FAILED", failure_reason=type(error).__name__)
            self._record("learning.offline_job.failed", state.job)
            return
        worker_status = result.worker.status
        if worker_status == "COMPLETED":
            self._update(
                state,
                status="COMPLETED",
                progress=1.0,
                training_run_id=result.training_run.id,
                candidate_policy_id=result.candidate.id,
                worker_status=worker_status,
            )
            self._record("learning.offline_job.completed", state.job)
        elif worker_status == "CANCELLED":
            self._update(
                state,
                status="CANCELLED",
                worker_status=worker_status,
                training_run_id=result.training_run.id,
                candidate_policy_id=result.candidate.id,
                failure_reason=result.worker.failure_reason,
            )
            self._record("learning.offline_job.cancelled", state.job)
        else:
            self._update(
                state,
                status="FAILED",
                worker_status=worker_status,
                training_run_id=result.training_run.id,
                candidate_policy_id=result.candidate.id,
                failure_reason=result.worker.failure_reason,
            )
            self._record("learning.offline_job.failed", state.job)

    def _refresh(self, state: _JobState) -> None:
        future = state.future
        if (
            future is not None
            and future.done()
            and state.job.status in {"QUEUED", "RUNNING", "CANCELLING"}
        ):
            try:
                future.result()
            except Exception as error:
                self._update(state, status="FAILED", failure_reason=type(error).__name__)

    def _update(self, state: _JobState, **changes: Any) -> None:
        with self._lock:
            state.job = state.job.model_copy(update={**changes, "updated_at": utc_now()})

    def _record(self, event_type: str, job: OfflineTrainingJob) -> None:
        self.repository.append_event(event_type, job.model_dump(mode="json"))

    def _load_durable(self, job_id: str) -> OfflineTrainingJob | None:
        for event in reversed(self.repository.list_events()):
            payload = event.payload
            if (
                isinstance(payload, dict)
                and payload.get("job_id") == job_id
                and event.event_type.startswith("learning.offline_job.")
            ):
                return OfflineTrainingJob.model_validate(payload)
        return None


__all__ = ["OfflineTrainingJob", "OfflineTrainingJobManager"]
