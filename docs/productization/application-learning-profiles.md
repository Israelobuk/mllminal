# Application interaction learning profiles

MLLminal learns a durable, provider-neutral interaction profile for each observed application. Profiles contain application identity, hashed executable location, redacted window metadata, semantic control roles and stable identifiers, keyboard shortcuts, menus and dialogs, visual anchor labels, observed state transitions, backend choices, reliability, fragility, and verification history.

Learning is deterministic and advisory-only. It uses existing Windows observation, semantic interaction capture, demonstrations, workflow compilation, provider resolution, verification, repair, and runtime outcomes. It never stores raw screenshots, window text, typed text, credentials, cookies, tokens, or secure-control values. Secure observations and sensitive interaction events are rejected before profile persistence.

## Backend resolution

Workflow actions request abstract capabilities such as `control.invoke`, `spreadsheet.inspect`, or `email.create_draft`. The interaction profile resolver considers only currently available backends and uses this safe hierarchy as its default:

`native.provider` → `browser.bridge` → `windows.uia` → `keyboard.shortcut` → `local.vision` → `relative.pointer`

Recorded reliability and verification evidence can select a more reliable available backend. The fixed hierarchy remains the tie-breaker when evidence is absent or equal. A resolution is visible through the daemon API and CLI, and no profile learning path sends email or bypasses approval.

## Current acceptance boundary

The capability-level acceptance gate proves profile persistence across restart, semantic control aggregation, stable identifier discovery, sensitive-data suppression, visible provider selection, reliability updates, idempotent experiences, and provider-neutral workflow candidates. Real Windows observation, UI Automation, browser bridge, screenshots/OCR, filesystem actions, compiler/repair recovery, desktop synchronization, installer behavior, and manual handoffs remain available for the machine-specific acceptance runbook.

No real Excel or classic Outlook acceptance result is claimed on the current machine. Those application-specific provider cases remain deferred only; they are not global product blockers. Spreadsheet and email capabilities must resolve through an available native, browser, bundled, portable, or manual provider, with exact rendering limitations stated honestly.
