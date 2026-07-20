# Acceptance results

## Current classification

Not certified. The acceptance state machine and runbook are implemented, but no clean Windows end-to-end run is recorded. The report returns real_windows_acceptance_required: true and keeps unresolved scenario, security, and performance checks manual-required. This is an evidence record, not a passing result.

## Evidence captured on 2026-07-20

| Area | Evidence | Result |
| --- | --- | --- |
| M1-M10 publication | PRs #30 through #39 merged into main | Implemented |
| M11 workflow | PR #40 merged; API, CLI, report, and runbook present | Implemented |
| Windows Explorer | explorer.exe present | Available |
| Excel desktop | EXCEL.EXE not detected | Blocked on this host |
| Classic Outlook COM | OUTLOOK.EXE not detected; olk.exe is not the supported COM path | Blocked on this host |
| Automatic send | No send capability is exposed | Disabled by design |
| Full weekly-report scenario | No run with real Explorer, Excel, Outlook, and desktop/CLI synchronization | Not run |
| Performance baseline | No clean-machine measurements recorded | Manual-required |

The absence of Excel and classic Outlook means this host cannot produce honest evidence for export and draft verification. No fixture substitution counts as real acceptance.

## Evidence required to close

On a clean Windows machine with supported Excel and Outlook, retain the acceptance run JSON, three real demonstrations, compiler output with labeled variables, preview and approval records, filesystem verification, Excel PDF verification, Outlook unsent-draft verification, desktop/CLI matching state, all security results, raw performance measurements, and final user review with the draft visibly unsent.

Record stages with:
mllminal acceptance record '{"stage":"observation_enabled","verified":true,"evidence":["<path>"],"note":"<operator note>"}'

Only a final user_reviewed record with verified evidence may move the run to passed. CI and simulated adapters can never infer that state.

## Readiness report

mllminal acceptance report returns scenario state, security checks, performance measurements, the no-automatic-send invariant, and the per-capability Production-capable/Beta/Prototype/Fixture-only/Deferred classification.
