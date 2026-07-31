# Security Findings

Date: 2026-07-30

## Confirmed protections

- Interaction text is metadata-only; secure/password/PIN/token/payment classifications are rejected by privacy policy.
- Action arguments reject password, secret, token, cookie, credential, and keystroke keys.
- Raw coordinate-only interactions are marked non-replayable.
- Replay requires separate authorization.
- Pydantic contracts reject unknown fields and malformed enum/shape values.
- Browser bridge and Windows UI seams avoid credential/cookie/token reads.
- Visual observations are semantic metadata only; no screenshot, OCR, camera, audio, or cloud-upload pipeline exists.
- All daemon routes are bearer-token protected except health.
- Filesystem and attachment paths reject traversal, symlink, and junction escapes and remain within approved roots.
- Mutations require preview, authorization, approval, idempotency, audit, and independent verification; destructive deletion uses the Recycle Bin where available.
- Emergency stop is consulted by bridge execution, bounded actions, workflow execution, and runtime policy decisions.
- Automatic policy promotion and retraining remain disabled during execution.
- Diagnostics export uses an allowlist and excludes tokens, databases, credentials, and session material.

## Fixed in the delivered baseline

- Workspace escape and forged verification were rejected in validation hardening.
- Bridge execution and bounded actions now honor durable emergency-stop state.
- Non-preview workflow runtime persistence is regression-tested.
- Generic capability discovery is bounded, provenance-bearing, and safe for unknown applications.
- Windows observer construction uses the native adapter set and the target Windows CI suite exercises lifecycle, callback, backpressure, and shutdown paths.
- The desktop client authenticates through the daemon, uses the daemon-owned state model, and cannot execute while disconnected or unauthorized.

## Open release findings

1. **Real external verification remains manual:** fixture and adapter verification are deterministic and persisted, but clean-machine acceptance must independently inspect real application state.
2. **No default unrestricted action executor:** approved bounded actions remain unavailable when a real executor is not configured; this is a safety-preserving limitation, not permission to add a shell fallback.
3. **Provider endpoint locality is configurable:** deployment policy must keep model/provider endpoints within the intended trust boundary.
4. **Filename sensitivity and retention require product policy:** authenticated local callers can receive approved filesystem metadata; future releases should define sensitivity and retention rules for names.
5. **Installer certification remains manual:** Inno compilation, signed-artifact review, clean install, startup, diagnostics, and uninstall behavior are not proven by repository CI.
6. **Optional provider evidence remains deferred:** native document/draft provider acceptance is host-dependent and must not be represented as global completion.

No credentials, tokens, cookies, passwords, or raw keystrokes were extracted during validation.