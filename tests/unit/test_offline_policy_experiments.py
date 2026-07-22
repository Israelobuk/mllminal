from mllminal.learning.contracts import PolicyDomain
from mllminal.learning.offline_experiments import record_local_experiment


def test_mlflow_experiment_tracking_stays_local(tmp_path) -> None:
    result = record_local_experiment(
        root=tmp_path,
        policy_domain=PolicyDomain.SUGGESTION_RANKING,
        snapshot_id="snapshot-1",
        feature_schema_version="training_features_v1",
        seed=7,
        parameters={"hidden_size": 8},
        metrics={"heuristic_accuracy": 0.5, "candidate_accuracy": 0.75},
    )

    assert result.run_id
    assert result.tracking_uri.startswith("sqlite:///")
    assert (tmp_path / "mlflow.db").exists()
