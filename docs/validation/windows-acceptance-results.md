# Windows Acceptance Results

Date: 2026-07-20
Host: Windows (`platform win32`), validation branch from `origin/main`.

## Important qualification

This was not a successful whole-device acceptance run. The daemon was started on Windows and returned `/v1/health` successfully, but the daemon constructs `DeviceObserver(..., [])`; no real Windows observer is wired. Interaction, demonstration, mining, and action inputs therefore remain API/service fixtures rather than physical mouse/keyboard/application activity.

## Results

| Acceptance step | Result | Evidence / limitation |
|---|---|---|
| Privacy and observation visibly enabled | Partial | Privacy API and status state are real and tested; no live desktop indicator is connected to daemon state. |
| Allowed semantic click/shortcut recorded | Partial | Privacy-filtered service and tests pass with caller-supplied semantic events; no Windows event producer is wired. |
| Secure text entry rejected | Proved at service level | Existing privacy/interaction tests cover secure classification and rejection; not a physical keyboard hook test. |
| Demonstration creates draft workflow | Partial | Durable demonstration service exists; no physical capture-to-draft run was proven. |
| Activity events become application/task session | Partial | Deterministic activity service exists; daemon observer has no adapters. |
| Repeated fixture sequence becomes workflow candidate | Not proven end-to-end | Mining implementation exists, but no dedicated subsystem test or persisted candidate review path exists. |
| Candidate becomes typed workflow | Not proven | No adapter connects mining candidates to `WorkflowDefinition` creation. |
| Preview shows planned effects | Proved in runtime path | `_preview_result` is deterministic and does not execute or inspect external state. |
| Bounded approved action executes | Partial | Injected executor path is tested; daemon default has no executor and returns `action_executor_not_configured`. |
| Result independently verified | Partial | Persisted bridge-result provenance is enforced; adapter verification checks returned metadata, not external application state. |
| Action and verification persisted | Partial | Bridge idempotency/result persistence is real; bounded action results are in-memory and not durable. |
| Desktop and CLI show the same task/event state | Not proven | Desktop is a static Textual dashboard and does not connect to daemon state. |
| Restart preserves state and replay | Partial | SQLite persistence and replay tests pass; no full multi-subsystem restart acceptance run. |
| Emergency stop blocks new actions | Proved at hardening boundary | New regression tests cover application bridge and bounded action gates. |

## Live Windows measurements

- Actual `mllminald.exe` reached `/v1/health` with `status=ok`.
- Health request latency: 84.31 ms in the sampled run.
- Daemon process working set: 4.25 MB; sampled CPU time: 0.031 seconds.

These measurements prove process startup and health response only, not whole-device acceptance.