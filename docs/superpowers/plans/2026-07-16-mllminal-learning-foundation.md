# MLLminal Learning Foundation Implementation Plan

> **For agentic workers:** Implement each task test-first and push every reviewed checkpoint to `origin/Israelobuk/mllminal-learning-foundation`.

**Goal:** Add safe local offline reward-weighted PyTorch policy learning without modifying Qwen or bypassing deterministic runtime safety.

**Base:** `5ff49422b0638640ba0dbfdb7cc1eeb1f0709832`

**Branch:** `Israelobuk/mllminal-learning-foundation`

## Global Constraints

- Python 3.12 and CPU-only PyTorch; no distributed or online reinforcement learning.
- Qwen remains frozen and raw messages never update policy weights.
- Policy recommendations are untrusted, safety-gated, masked, and advisory.
- Permissions, approvals, workspace confinement, tool schemas, task transitions, and verification remain authoritative.
- Learning defaults enabled; automatic promotion defaults disabled; explicit promotion is required.
- Seed 42, minimum 100 eligible experiences, replay capacity 10,000, confidence threshold 0.65.
- Push every coherent commit and keep the draft PR current.

## Tasks

1. Add versioned learning contracts, the fixed 15-value feature encoder, action masks, eligibility rules, and transparent weighted rewards.
2. Add migration `0003`, durable learning settings, decisions, experiences, replay entries, global events, runs, evaluations, policies, promotions, and rollbacks.
3. Add the `15 → 64 → 32 → 9` PyTorch policy, deterministic inference/checkpoints, offline training, candidate evaluation, registry, explicit promotion, and rollback.
4. Integrate safety-gated recommendations and terminal experience finalization into the existing Mil runtime without changing disabled-learning behavior.
5. Add authenticated learning REST/WebSocket APIs, complete Typer commands, status output, and local-learning documentation.
6. Run the full release gate, deterministic promotion/rejection/restart/rollback acceptance scenario, final review, and draft-PR handoff.

