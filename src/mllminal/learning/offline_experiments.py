"""Lazy local MLflow recording for offline advisory-policy runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mllminal.learning.contracts import PolicyDomain


@dataclass(frozen=True)
class LocalExperimentResult:
    run_id: str
    tracking_uri: str


def record_local_experiment(
    *,
    root: Path,
    policy_domain: PolicyDomain,
    snapshot_id: str,
    feature_schema_version: str,
    seed: int,
    parameters: dict[str, Any],
    metrics: dict[str, float],
) -> LocalExperimentResult:
    """Record one offline run in a local SQLite-backed MLflow store on demand."""

    import mlflow

    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    tracking_database = root / "mlflow.db"
    tracking_uri = f"sqlite:///{tracking_database.as_posix()}"
    artifact_directory = root / "mlartifacts"
    artifact_directory.mkdir(parents=True, exist_ok=True)
    experiment_name = f"mllminal-{policy_domain.value.lower()}"

    mlflow.set_tracking_uri(tracking_uri)
    if mlflow.get_experiment_by_name(experiment_name) is None:
        mlflow.create_experiment(
            experiment_name,
            artifact_location=artifact_directory.as_uri(),
        )
    mlflow.set_experiment(experiment_name)
    with mlflow.start_run() as run:
        mlflow.log_params(
            {
                "policy_domain": policy_domain.value,
                "snapshot_id": snapshot_id,
                "feature_schema_version": feature_schema_version,
                "seed": seed,
                **parameters,
            }
        )
        mlflow.log_metrics(metrics)
        return LocalExperimentResult(run.info.run_id, tracking_uri)
