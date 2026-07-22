"""Deterministic builders for immutable advisory-policy replay metadata."""

from __future__ import annotations

import hashlib
import json
from collections import Counter

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
