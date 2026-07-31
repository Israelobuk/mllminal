# MLLminal Windows technical preview packaging

Build the wheel from the repository root with `uv build`, copy it under `packaging/windows/dist`, and compile `MLLminal.iss` with Inno Setup 6. The installer creates a private Python environment, installs the CLI/daemon/desktop entry points, initializes a provider-neutral first-run policy, and never enables observation, external submission, or model downloads automatically.

The first-run policy explains metadata-only observation, excluded capture classes, discovered application surfaces, bounded provider capabilities, disabled permissions, pause/emergency controls, local data location, and history deletion. The core inventory covers the Windows observer, workspace filesystem, browser bridge, and manual handoff. Optional provider-specific entries may appear when detected, but they never change the deterministic safety boundary.

`install.ps1` writes `first-run.json` and a versioned `provider-inventory.json` with bounded capability lists, provenance, detection state, and safety notes. `doctor.ps1` produces a read-only JSON health report for the installed runtime. `export-diagnostics.ps1` includes those reports, Windows information, and hardware output while excluding tokens, databases, credentials, and session material.

Startup-at-login is opt-in through `install.ps1 -EnableStartup`. Uninstall retains local history by default; `uninstall.ps1 -DeleteData` explicitly removes it. Lightweight mode skips optional portable providers and never silently downloads one.
