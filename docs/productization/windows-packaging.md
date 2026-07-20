# Windows installer and first-run packaging

Milestone 10 provides an Inno Setup installer plus PowerShell install, uninstall, and diagnostics scripts under `packaging/windows`.

The installer installs the daemon, CLI, and `mllminal-ui` desktop entry points into a private local Python environment, initializes local data, and writes a first-run policy with observation disabled. It explains metadata-only observation, what is never captured, detected applications, disabled permissions, pause/emergency controls, local data location, and history deletion. Startup-at-login is optional and never enables observation by itself.

Uninstall removes the application but retains history by default. Complete local deletion requires the explicit `-DeleteData` switch. Diagnostics export includes logs, first-run configuration, provider configuration, Windows information, and the hardware profile while excluding the token, database, credentials, and session material.

`mllminal system hardware` and `/v1/system/hardware` report CPU, available memory, GPU availability, Windows version, UI Automation, local OCR, model availability, and a Light/Standard/High capability recommendation. No model is downloaded, launched, or changed without user confirmation.

Build: run `uv build`, copy the wheel to `packaging/windows/dist`, then compile `packaging/windows/MLLminal.iss` with Inno Setup 6 on Windows.
