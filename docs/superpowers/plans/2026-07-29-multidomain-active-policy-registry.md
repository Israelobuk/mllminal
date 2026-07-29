# Multi-Domain Active Policy Registry Implementation Plan

**Goal:** Add the durable domain-scoped binding layer required before shadow evaluation and additional runtime adapters.

**Architecture:** Keep existing `PolicyVersion` lifecycle and artifacts as the candidate source of truth. Add an `ActivePolicyBinding` contract and SQLite payload table keyed by policy domain. `ActivePolicyRegistry` validates domain/schema/action/runtime compatibility, artifact digest, bounded configuration, and explicit activation. It permits at most one ACTIVE binding per domain, allows SHADOW bindings to coexist, records the previous binding for rollback, and exposes deterministic fallback when no valid binding exists. Runtime inference remains owned by domain adapters; this slice only owns binding state and lifecycle.

## Tasks

- [ ] Add typed binding status/config contracts with bounded advisory weight, confidence, latency, circuit configuration, compatibility metadata, and safe fallback policy.
- [ ] Add durable binding persistence and repository methods with idempotent activate, disable, list, get, and rollback operations.
- [ ] Add registry validation for policy domain, artifact digest/path confinement, feature/action schema, runtime compatibility, and one-active-per-domain isolation.
- [ ] Add focused tests for multi-domain coexistence, shadow coexistence, restart durability, invalid compatibility, digest failure, idempotency, disable, and rollback.
- [ ] Add authenticated daemon and daemon-backed CLI surfaces for active policy bindings.
- [ ] Run focused tests, Ruff, mypy, full suite, push PR A, squash-merge, and delete its branches.

## Safety invariants

- Binding activation is explicit and never triggered by runtime inference or training.
- No binding changes permissions, approvals, consequence classes, eligibility, or emergency-stop behavior.
- Artifact paths stay under the configured learning artifact directory; raw input data is never stored.
- A missing, invalid, disabled, or rolled-back binding means deterministic fallback.