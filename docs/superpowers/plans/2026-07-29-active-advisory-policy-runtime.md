# Active Advisory Policy Runtime Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Activate promoted `BACKEND_RANKING` PyTorch artifacts as bounded, advisory-only inputs to deterministic backend selection, with durable provenance, safe fallback, circuit breaking, and authenticated daemon/CLI/desktop status.

**Architecture:** Keep `AdaptiveExecutionService` authoritative for emergency stop, availability, permissions, verification, and clarification. Add a backend runtime adapter that resolves the promoted domain policy, validates the stored digest and `training_features_v1` schema, encodes only bounded allowlisted backend features, and returns bounded per-backend advisory scores. The service combines those scores only among already eligible candidates, persists both score components and explanation fields in the existing decision JSON, and trips an in-process circuit breaker after repeated runtime failures. A single status projection is reused by daemon, CLI, and desktop.

**Tech Stack:** Python 3.12, Pydantic contracts, SQLAlchemy JSON payload persistence, FastAPI, Typer, Textual, PyTorch CPU inference, pytest.

## Global Constraints

- `BACKEND_RANKING` is the only active runtime domain in this milestone.
- Deterministic eligibility remains authoritative; the model cannot select a rejected or ineligible backend.
- Emergency stop, permissions, approvals, verification, and clarification behavior remain unchanged.
- Runtime execution never promotes, retrains, mutates artifacts, or performs device I/O.
- Artifact digest, domain, feature schema, dimensions, finite bounded output, and inference timeout/budget are validated before advisory scores are used.
- Missing, rolled-back, incompatible, corrupted, or failing policies fall back to deterministic ranking and are visible in provenance/status.
- Preserve legacy decisions and existing public APIs; new fields are optional/defaulted for old payloads.

## Tasks

- [ ] **Task 1: Add backend runtime contracts and feature encoding.**
  - Files: `src/mllminal/learning/adaptive_contracts.py`, `src/mllminal/learning/backend_runtime.py`, `src/mllminal/learning/offline_features.py`.
  - Add typed advisory score/provenance/status records with bounded values and explicit fallback reasons.
  - Add a deterministic encoder from `AdaptiveExecutionRequest`, candidate, profile, and reliability evidence to the existing `BACKEND_RANKING` feature names, with finite `[0, 1]` values and no raw payloads.
  - Define a fixed inference budget and a circuit-breaker state that is local to the daemon/service instance.

- [ ] **Task 2: Implement active artifact loading and isolated inference.**
  - Files: `src/mllminal/learning/backend_runtime.py`, `src/mllminal/learning/offline_training.py`, `tests/unit/test_backend_runtime.py`.
  - Resolve the promoted policy by `PolicyDomain.BACKEND_RANKING`; treat `policy_v0` or a domain mismatch as inactive.
  - Verify checkpoint existence and SHA-256 against `PolicyVersion.checkpoint_sha256`, load with the existing CPU-only offline loader, require `training_features_v1`, the expected dimension, and finite bounded output.
  - Score only candidate backend labels, bound inference work to the configured local budget, and trip/open the circuit after repeated failures; reset on a successful load/inference.
  - Test digest mismatch, schema mismatch, missing active artifact, malformed output, repeated failures, recovery, and rollback-to-fallback.

- [ ] **Task 3: Integrate advisory scores into deterministic backend ranking.**
  - Files: `src/mllminal/learning/adaptive.py`, `src/mllminal/learning/adaptive_contracts.py`, `tests/unit/test_adaptive_execution.py`, `tests/unit/test_backend_runtime.py`.
  - Keep the current deterministic filters and rank key as the first stage.
  - Combine a bounded advisory score with each eligible candidate’s deterministic score using a documented conservative weight; never score or select rejected candidates.
  - Persist deterministic score, advisory score, combined score, active policy identity/digest/schema, fallback/circuit state, and a complete human-readable explanation in the existing durable decision payload.
  - Ensure emergency-stop and permission rejection still produce no model influence and remain training-ineligible where already required.

- [ ] **Task 4: Expose active-policy runtime status through daemon, CLI, and desktop.**
  - Files: `src/mllminal/daemon/api.py`, `src/mllminal/cli/main.py`, `src/mllminal/client/api.py`, `src/mllminal/client/app.py`, related API/CLI tests.
  - Add an authenticated backend runtime status projection showing domain, active policy/version/digest, schema validation, advisory enabled/weight, circuit state, last fallback reason, and automatic-promotion/retraining disabled flags.
  - Include status in desktop snapshots and render a compact policy line without changing action controls or authority boundaries.
  - Keep all existing learning lifecycle endpoints unchanged and ensure runtime status is read-only.

- [ ] **Task 5: Add acceptance, rollback, and safety regression coverage.**
  - Files: `tests/unit/test_backend_runtime.py`, `tests/unit/test_adaptive_execution.py`, `tests/integration/test_adaptive_api.py`, `tests/unit/test_cli_adaptive.py`, desktop client tests if present.
  - Cover active artifact influence among eligible backends, deterministic tie/safety behavior, fallback after inference failure, circuit recovery, persisted provenance/explanation, API authentication, CLI JSON, desktop status, rollback, emergency stop, permissions, approvals, verification, and “no promotion/retraining during decide”.
  - Run focused tests, lint/type checks available in `pyproject.toml`, then the complete suite and inspect the final diff.

## Verification Commands

```powershell
uv run pytest tests/unit/test_backend_runtime.py tests/unit/test_adaptive_execution.py tests/integration/test_adaptive_api.py tests/unit/test_cli_adaptive.py
uv run ruff check src tests
uv run mypy src
uv run pytest
```

## Commit/PR Handoff

- Branch: `Israelobuk/mllminal-active-advisory-policy-runtime`
- PR title: `Activate advisory policy runtime for backend ranking`
- Do not merge automatically; report the commit, pushed branch, PR, and validation results.
