# Windows Device Observer — Milestone 1 Plan

## Scope

Create a metadata-only, consent-gated device observer foundation. It accepts deterministic fake Windows adapter signals in CI and exposes bounded observer lifecycle/status/capabilities/event replay. It has no execution authority.

## Exclusions

No keystrokes, typed text, screen pixels, audio, camera, clipboard history, browser-page content, credentials, privacy-rule engine, workflow mining, or device actions.

## Checkpoints

1. Add versioned device contracts and strict normalization that rejects forbidden/raw payload fields.
2. Add durable observer settings, event storage, monotonic sequence, duplicate suppression, and restart-safe status.
3. Add bounded queue collector, fake adapter, lifecycle controls, health/capabilities, and dropped-event accounting.
4. Add authenticated API/WebSocket replay and Typer `device` commands; persist before publication.
5. Document observer metadata/exclusions, run full release checks, push, and open a draft PR.

## Safety invariants

- Observation defaults disabled and must be explicitly started.
- Only normalized metadata is persisted.
- Rejected/forbidden raw signals are never stored.
- The observer cannot invoke tools, approvals, workflows, or runtime actions.
- Adapter failures are isolated and reflected in health status.
