"""Short-lived isolated local workers for offline policy training."""

from __future__ import annotations

import multiprocessing
import os
from dataclasses import dataclass
from queue import Empty

from mllminal.learning.contracts import TrainingExperience
from mllminal.learning.offline_features import TrainingFeatureEncoder
from mllminal.learning.offline_training import OfflineTrainingConfig, train_offline_candidate


@dataclass(frozen=True)
class TrainingWorkerResult:
    status: str
    action_labels: tuple[str, ...] = ()
    losses: tuple[float, ...] = ()
    worker_pid: int | None = None
    failure_reason: str | None = None


def run_isolated_training(
    experiences: list[TrainingExperience],
    encoder: TrainingFeatureEncoder,
    config: OfflineTrainingConfig,
    *,
    timeout_seconds: float,
) -> TrainingWorkerResult:
    """Train in one spawned process and return only safe summary metadata."""

    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    process = context.Process(
        target=_train_in_worker,
        args=(result_queue, experiences, encoder, config),
        daemon=False,
    )
    process.start()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join()
        return TrainingWorkerResult(status="TIMED_OUT", failure_reason="training_timeout")
    try:
        result = result_queue.get(timeout=1)
    except Empty:
        return TrainingWorkerResult(status="FAILED", failure_reason="worker_crashed")
    return TrainingWorkerResult(**result)


def _train_in_worker(
    result_queue: multiprocessing.queues.Queue[dict[str, object]],
    experiences: list[TrainingExperience],
    encoder: TrainingFeatureEncoder,
    config: OfflineTrainingConfig,
) -> None:
    try:
        result = train_offline_candidate(experiences, encoder, config)
        result_queue.put(
            {
                "status": "COMPLETED",
                "action_labels": result.action_labels,
                "losses": result.losses,
                "worker_pid": os.getpid(),
            }
        )
    except Exception as error:
        result_queue.put({"status": "FAILED", "failure_reason": type(error).__name__})
