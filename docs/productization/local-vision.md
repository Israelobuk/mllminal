# Bounded local vision runtime

Milestone 3 adds a Windows-only, local visual inspection path for bounded screenshots. It is an inspection and verification aid; it does not grant click, typing, file, browser, or application execution authority.

## Capture contract

- `active_window` captures the foreground application window.
- `bounded_application` and `user_selected_region` limit capture to a caller-supplied region within that foreground window.
- `verification_frame` is intended for a single expected-state check.
- `demonstration_fallback` is a bounded fallback mode for demonstration review.
- Sensitive regions are blacked out in the in-memory pixel buffer before the frame is written.
- Temporary frames are deleted in a `finally` block. Debug retention is opt-in, limited to five minutes, cleaned by age, and stored separately from normal frames.

The runtime uses Windows GDI for one-shot capture and never starts a continuous full-screen recording. It rejects secure dialogs and relies on the existing privacy decision before capturing. Captured frames are never uploaded.

## Local inspection

`LocalVisionProvider` is provider-neutral and local-only. It can use Windows UI Automation for focused semantic controls and optional local Tesseract OCR for visible text. Results are structured as role, redacted semantic name, bounds, state flags, confidence, and provider availability. It can identify visible loading/error/dialog text, but it does not execute a consequential action from visual confidence alone.

The daemon endpoint is `POST /v1/vision/inspect`; the CLI equivalent is:

```powershell
mllminal visual inspect '{"mode":"verification_frame","expected":[{"role":"text","semantic_name":"Ready"}]}'
```

When `expected` anchors are supplied, the response includes deterministic local verification from the recorded observation. This does not replace capability, approval, or postcondition checks.

## Acceptance status

- Real: Windows GDI active-window capture, bounded region clipping, sensitive-region masking, privacy decisions, temporary cleanup, structured local observation, and deterministic anchor matching are implemented.
- Simulated/fixture: provider behavior without a live Windows desktop remains represented by contracts and injected provider interfaces for CI.
- Manual: acceptance requires a real Windows desktop and File Explorer routine: inspect a non-sensitive test folder, verify a visible anchor, confirm a masked region, confirm a retained debug frame expires, and confirm secure-window capture is rejected.
- Unsupported: non-Windows hosts, secure windows, unavailable UI Automation/OCR providers, and regions outside the active window are reported or rejected without cloud fallback.

The runtime is intentionally not a general screen reader, browser scraper, OCR archive, or autonomous UI controller.
