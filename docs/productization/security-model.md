# Security model

MLLminal is local-first and approval-controlled. Mil may interpret intent, but cannot bypass the typed workflow runtime, capability registry, permission grants, approval state, independent verification, or emergency stop.

## Enforced boundaries

Observation is explicit, visible, pausable, and stoppable. Secure controls are classified before persistence; raw typed characters, clipboard content, credentials, tokens, and secure-field content are suppressed. Filesystem and attachment paths are normalized, confined to approved roots, and reject traversal, symlinks, and junction escapes. Mutations require preview, authorization, idempotency, audit, and independent verification. Destructive filesystem behavior uses the Recycle Bin where available. Excel is read-only by default, disables link updates, identifies macro-enabled files, and closes without saving after failures. Email exposes draft-only operations and no send capability. Authenticated desktop clients cannot execute while disconnected or unauthorized. Bounded visual frames are masked, temporary by default, and never uploaded to an MLLminal cloud service.

## Security test procedure

Exercise secure input suppression; malicious workflow definitions; path traversal, junction, and symlink escape; permission bypass and replay without authorization; forged verification and duplicate execution after restart; emergency-stop bypass and stale approvals; application identity spoofing; malicious OCR and visual prompt injection; adapter crash; corrupted persisted state; unauthorized desktop clients; and browser-bridge origin spoofing if a bridge is enabled.

Retain input, observed output, audit event, and independent verifier result for each case. A fixture or unit test is not real desktop evidence.

## Local-only guarantee and status

The repository contains no MLLminal-operated upload path for screenshots, OCR output, workflow history, file contents, prompts, or activity events. Network traffic from Outlook, OneDrive, Gmail, or other user applications is separate and must be disclosed.

Code-level controls are reported as implemented. Adversarial desktop, OCR, prompt-injection, and unauthorized-client checks remain manual-required until exercised on a clean Windows session.
