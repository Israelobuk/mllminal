# Real workflow demonstration

Milestone 2 connects the merged Windows observation runtime to Demonstration Mode. When visible observation is enabled and a demonstration session is recording, normalized device events are converted into typed `InteractionEvent` records and persisted through the existing privacy service.

## Real paths

- Foreground application/window transitions become non-replayable application/window focus steps.
- UI Automation-backed clicks become semantic `control.invoked` steps with application, redacted window classification, role, accessible name when non-sensitive, and automation id.
- Coordinate-only clicks are retained as fragile, non-replayable steps.
- Shortcuts, navigation, Enter, Escape, Tab, and scroll direction/amount buckets become typed interaction steps.
- Text entry records occurrence and field metadata only; it never records characters.
- Normalized file event types are retained as inactive file-operation steps for later real filesystem adapters.
- Every bridge write uses the observer event id as an idempotency key.

## User workflow

1. Run `mllminal observe enable` and configure the desired semantic/shortcut metadata modes.
2. Run `mllminal demonstrate start "Weekly report"`.
3. Perform the routine in a real Windows application or File Explorer.
4. Run `mllminal demonstrate status`, `steps`, and `stop` to produce an inactive draft candidate.
5. Label values with fixed, ask-each-run, selected-file, current-date, saved-contact, previous-output, skip-step, or never-automate labels.

A candidate remains inactive. It records fragile steps, approval points, required capabilities, verification requirements, and unsupported-step slots for later compiler and adapter milestones.

## Privacy and acceptance

Secure controls are classified before persistence. Secure keyboard input produces at most one minimized rejection event per focused secure field and no characters. Demonstration events pass through the existing consent, exclusion, pause, incognito, and emergency-stop gates.

Automated coverage remains contract and fixture coverage in CI. Manual acceptance still requires a real Windows File Explorer routine: enable visible observation, start recording, select and rename a non-sensitive test file, pause/resume, stop, review the draft, and confirm the candidate is inactive and coordinate-only actions are marked fragile.

This milestone does not execute candidates, capture screenshots, automate Excel/email, or infer final variables automatically. Those remain separate milestones.
