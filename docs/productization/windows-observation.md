# Windows observation runtime

Milestone 1 connects the daemon to a real Windows metadata observer. When `/v1/device/start` or `mllminal device start` enables observation, the runtime polls native process and foreground-window APIs, UI Automation focus metadata, and a low-level Windows input hook. Events are persisted locally before they are published to subscribers.

## Real Windows paths

- Process lifecycle uses `pywin32` process enumeration and executable-path lookup when `psutil` is unavailable.
- Foreground transitions use `win32gui` and `win32process`; window titles are classified and never persisted.
- Focused controls use `UIAutomationClient.CUIAutomation8`; only control type, automation id, class name, and secure-field status are retained.
- Mouse and keyboard hooks emit only semantic metadata: click, double-click, scroll direction, navigation, confirm/cancel, tab direction, and modifier shortcuts. Typed characters are never converted or stored.
- UI Automation invocation is an explicit approved operation and is not performed by observation.

Unavailable native APIs remain visible as unavailable capabilities and do not stop the daemon. Adapter exceptions are isolated in observer health state. Pause and stop halt ingestion; shutdown unhooks native input callbacks.

## Privacy and safety boundary

The collection boundary rejects forbidden raw payload fields, drops window-title content during normalization, suppresses keyboard events while a secure UI Automation control is focused, and does not capture screenshots, clipboard contents, audio, camera input, browser content, credentials, or typed text. Observation has no workflow execution authority.

## Acceptance status

Automated repository coverage remains fixture-based and validates contracts, persistence, queue bounds, lifecycle state, and adapter failure isolation. The native adapter path is implemented for a real Windows session but requires manual acceptance on that session with File Explorer, a normal document window, a secure input control, pause/resume, process restart, and emergency stop. This branch does not claim those manual checks were completed.

## Known limits

The native observer is intentionally metadata-only. It does not yet compile demonstrations, inspect screenshots, drive Excel or email, or recover workflows. Those are later milestones and must remain separate branches and pull requests.
