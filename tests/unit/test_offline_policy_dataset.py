from pathlib import Path

import duckdb

from mllminal.learning.contracts import PolicyDomain, TrainingExperience
from mllminal.learning.offline import materialize_replay_snapshot


def test_snapshot_materialization_writes_queryable_local_parquet(tmp_path: Path) -> None:
    experience = TrainingExperience(
        policy_domain=PolicyDomain.SUGGESTION_RANKING,
        source_record_type="suggestion_feedback",
        source_record_id="feedback-1",
        context_features={"occurrence_count": 6.0},
        candidate_actions=("present", "defer"),
        selected_action="present",
        baseline_score=0.7,
        reward=1.0,
        reward_components={"accepted": 1.0},
        privacy_approved=True,
        eligible_for_training=True,
    )

    snapshot = materialize_replay_snapshot(
        [experience],
        policy_domain=PolicyDomain.SUGGESTION_RANKING,
        seed=7,
        root=tmp_path,
    )

    assert snapshot.storage_path is not None
    assert Path(snapshot.storage_path).suffix == ".parquet"
    assert duckdb.sql(
        "SELECT count(*) FROM read_parquet(?)", params=[snapshot.storage_path]
    ).fetchone() == (1,)
