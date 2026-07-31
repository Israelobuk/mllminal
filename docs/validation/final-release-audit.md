# Final security, recovery, and release audit

Date: 2026-07-30
Repository: `Israelobuk/mllminal`
Validation base: `origin/main` at `3a5dde817cab84bd2ba064cc700acefcbc43dbe1`

## Result

MLLminal is ready for a Windows technical-preview baseline. The deterministic safety boundary remains authoritative, application capability discovery is bounded and provider-neutral, learning remains advisory/offline, and the installed runtime does not enable observation, external submission, automatic execution, model download, automatic promotion, or automatic retraining by default.

This is not a clean-machine production certification. Real application-state verification, a signed Inno Setup artifact, clean install/uninstall retention, and optional provider-specific acceptance remain manual release gates.

## Evidence

- Windows GitHub Actions CI (`windows-latest`, run `30593095849`): checkout, locked dependency sync, Ruff, format check, mypy, and full pytest all passed.
- Full local suite: 257 passed, 4 expected dependency warnings.
- Focused security/recovery/governance/packaging suite: 20 passed.
- Source quality: repository Ruff check and format check passed; mypy passed for 158 source files.
- Windows packaging: all PowerShell sources parsed with Windows PowerShell 5.1; `doctor.ps1` returned a safe report for an absent installation without creating files.
- Release hygiene: PRs #96 through #105 were pushed, CI-verified, squash-merged, and their remote/local feature branches were deleted.

## Safety and security closure

- Observation is metadata-only, privacy-gated, pausable, and emergency-stoppable; secure text, credentials, cookies, tokens, screenshots, and raw keystrokes are excluded.
- Capability discovery reports bounded registered adapters with provider/source provenance. Unknown or unavailable applications fail safely without inventing capabilities.
- Mutations require preview, workflow authorization, explicit approval, idempotency, audit persistence, and verification. Rollback carries its own typed verification boundary.
- Provider resolution and execution never add an ineligible capability. Draft paths remain unsent, and no `email.send` capability is exposed.
- Daemon routes and desktop clients use bearer-token authentication; the desktop surface remains a thin daemon client and cannot become an independent execution authority.
- Adaptive learning and policy runtime status keep automatic promotion and retraining disabled. Runtime decisions remain deterministic-authority first.
- Diagnostics use an allowlist and exclude tokens, databases, credentials, and session material.

## Recovery and release closure

- Duplicate requests are protected by persisted idempotency keys across application and workflow paths.
- Failed or interrupted workflow steps retain durable run state, attempts, checkpoints, verification, and rollback information.
- Emergency stop and stale approval checks execute before action acceptance.
- Windows CI exercises the full suite on the target operating-system family, including observer, callback, lifecycle, backpressure, and shutdown regression coverage.
- The installer records a versioned first-run policy and provider inventory; `doctor.ps1` gives a read-only runtime/safety report; uninstall retains local history unless `-DeleteData` is explicit.

## Remaining manual gates

1. Compile and review the Inno Setup installer on a clean Windows account.
2. Verify install, startup opt-in, daemon launch, diagnostics export, and uninstall retention/deletion behavior.
3. Exercise real Windows UI Automation and application-state verification with non-sensitive fixtures.
4. Record optional native document/draft provider evidence only when those providers are present; provider-neutral acceptance does not depend on them.

## Decision

The repository is a clean, safety-bounded Windows technical-preview baseline for the next product milestone: Active Advisory Policy Runtime Integration. The model must remain advisory and bounded when that milestone begins; deterministic eligibility, permissions, approvals, emergency stop, verification, and rollback remain authoritative.