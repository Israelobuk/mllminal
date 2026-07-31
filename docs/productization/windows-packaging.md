# Windows installer and first-run packaging

Milestone 10 provides an Inno Setup installer plus PowerShell install, uninstall, and diagnostics scripts under `packaging/windows`.

The installer installs the daemon, CLI, and `mllminal-ui` desktop entry points into a private local Python environment, initializes local data, and writes a versioned provider-neutral first-run policy with observation disabled. It records bounded capability discovery for the Windows observer, workspace filesystem, browser bridge, and manual handoff, while optional provider-specific entries remain explicitly optional. Startup-at-login is optional and never enables observation by itself.

Uninstall removes the application but retains history by default. Complete local deletion requires the explicit `-DeleteData` switch. The read-only `doctor.ps1` report and diagnostics export include first-run configuration, provider inventory, runtime checks, Windows information, and the hardware profile while excluding the token, database, credentials, and session material.

`mllminal system hardware` and `/v1/system/hardware` report CPU, available memory, GPU availability, Windows version, UI Automation, local OCR, model availability, and a Light/Standard/High capability recommendation. No model is downloaded, launched, or changed without user confirmation.

Build: run `uv build`, copy the wheel to `packaging/windows/dist`, then compile `packaging/windows/MLLminal.iss` with Inno Setup 6 on Windows. Validate the PowerShell sources with the Windows PowerShell parser and run `doctor.ps1` after installation.
