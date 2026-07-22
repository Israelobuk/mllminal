"""Deterministic builders for immutable advisory-policy replay metadata."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from mllminal.learning.contracts import PolicyDomain, ReplaySnapshot, TrainingExperience


def build_replay_snapshot(
    experiences: list[TrainingExperience], *, policy_domain: PolicyDomain, seed: int
) -> ReplaySnapshot:
    """Freeze eligible domain evidence into canonical, reproducible snapshot metadata."""

    included = sorted(
        (
            experience
            for experience in experiences
            if experience.policy_domain is policy_domain
            and experience.privacy_approved
            and experience.eligible_for_training
        ),
        key=lambda experience: (
            experience.source_record_type,
            experience.source_record_id,
            experience.experience_id,
        ),
    )
    excluded = [
        experience
        for experience in experiences
        if experience.policy_domain is policy_domain and experience not in included
    ]
    exclusion_reasons = Counter(
        experience.exclusion_reason or "ineligible" for experience in excluded
    )
    payload = [
        experience.model_dump(mode="json", exclude={"experience_id", "created_at"})
        for experience in included
    ]
    dataset_digest = _digest(payload)
    included_ids = tuple(experience.experience_id for experience in included)
    split_digest = _digest({"experience_ids": included_ids, "seed": seed})
    created = [experience.created_at for experience in included]
    return ReplaySnapshot(
        policy_domain=policy_domain,
        source_window_start=min(created) if created else None,
        source_window_end=max(created) if created else None,
        experience_count=len(included),
        included_experience_ids=included_ids,
        excluded_experience_count=len(excluded),
        exclusion_reasons=dict(sorted(exclusion_reasons.items())),
        dataset_digest=dataset_digest,
        split_digest=split_digest,
        random_seed=seed,
    )


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def materialize_replay_snapshot(
    experiences: list[TrainingExperience],
    *,
    policy_domain: PolicyDomain,
    seed: int,
    root: Path,
) -> ReplaySnapshot:
    """Write one immutable, minimized Parquet replay dataset for offline use."""

    snapshot = build_replay_snapshot(experiences, policy_domain=policy_domain, seed=seed)
    included = [
        experience
        for experience in experiences
        if experience.experience_id in set(snapshot.included_experience_ids)
    ]
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{snapshot.dataset_digest}.parquet"
    if not path.exists():
        table = pa.table(
            {
                "experience_id": [item.experience_id for item in included],
                "policy_domain": [item.policy_domain.value for item in included],
                "source_record_type": [item.source_record_type for item in included],
                "source_record_id": [item.source_record_id for item in included],
                "context_features_json": [
                    json.dumps(item.context_features, sort_keys=True) for item in included
                ],
                "candidate_actions_json": [json.dumps(item.candidate_actions) for item in included],
                "selected_action": [item.selected_action for item in included],
                "baseline_score": [item.baseline_score for item in included],
                "reward": [item.reward for item in included],
                "reward_components_json": [
                    json.dumps(item.reward_components, sort_keys=True) for item in included
                ],
                "reward_formula_version": [item.reward_formula_version for item in included],
            }
        )
        pq.write_table(table, path, compression="zstd")  # type: ignore[no-untyped-call]
    return snapshot.model_copy(update={"storage_path": str(path)})
