# Security Findings

Date: 2026-07-20

## Fixed in validation hardening

- **Workspace escape:** filesystem paths are resolved and rejected unless they remain under the configured workspace root. This applies to inspection and copy-draft source/destination plans.
- **Emergency-stop bypass:** bridge execution and bounded actions consult the durable privacy emergency-stop state before accepting preview or execution requests.
- **Workflow runtime crash:** mutable workflow runtime state is now represented by a non-frozen runtime model; a real non-preview fixture execution is regression-tested.
- **Verification forgery:** application verification requires an exact persisted bridge execution result; modified caller payloads are rejected.

## Confirmed protections

- Interaction text is metadata-only; secure/password/PIN/token/payment classifications are rejected by privacy policy.
- Action arguments reject password, secret, token, cookie, credential, and keystroke keys.
- Raw coordinate-only interactions are marked non-replayable.
- Replay requires separate authorization.
- Pydantic contracts reject unknown fields and malformed enum/shape values.
- Browser bridge and UI seams explicitly avoid credential/cookie/token reads.
- Visual observations are semantic metadata only; no screenshot, OCR, camera, audio, or cloud upload pipeline exists.
- All daemon routes are bearer-token protected except health.

## Open findings

1. **No real action executor:** the daemon’s bounded-action service has no default OS executor; approved requests return `action_executor_not_configured`. This prevents silent unsafe behavior but blocks real Windows acceptance.
2. **External verification is absent:** workflow and adapter verification evaluate deterministic result payloads; they do not independently inspect real application state.
3. **Device observer is disconnected:** daemon construction passes an empty adapter list. Existing Windows process and fake adapters are not part of the live daemon path.
4. **Provider URL is configurable:** the local model provider can be pointed at a non-loopback URL; local-only data flow is not technically enforced by configuration.
5. **Desktop dashboard is static:** it has no daemon authentication, streaming, approval, reconnect, or error-state path.
6. **Filesystem read is bounded but not content-redacted:** directory names are returned to an authenticated local caller. A future policy decision should define filename sensitivity and retention.

No credentials, tokens, cookies, passwords, or raw keystrokes were extracted during validation.