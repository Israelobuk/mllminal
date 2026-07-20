# MLLminal Windows packaging

Build the wheel from the repository root with `uv build`, copy it under `packaging/windows/dist`, and compile `MLLminal.iss` with Inno Setup 6. The installer creates a private Python environment, installs the CLI/daemon/desktop entry points, initializes a first-run policy, and never enables observation or downloads/launches a model automatically.

The first-run policy explains metadata-only observation, excluded capture classes, detected applications, disabled permissions, pause/emergency controls, local data location, and history deletion. Startup-at-login is opt-in through `install.ps1 -EnableStartup`. Uninstall retains local history by default; `uninstall.ps1 -DeleteData` explicitly removes it. `export-diagnostics.ps1` excludes tokens, databases, and credentials.

Hardware recommendations are available with `mllminal system hardware` and the authenticated daemon endpoint `/v1/system/hardware`. Profiles are Light, Standard, and High capability. A profile never starts a model or downloads dependencies without confirmation.
