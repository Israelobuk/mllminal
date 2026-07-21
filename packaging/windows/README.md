# MLLminal Windows packaging

Build the wheel from the repository root with `uv build`, copy it under `packaging/windows/dist`, and compile `MLLminal.iss` with Inno Setup 6. The installer creates a private Python environment, installs the CLI/daemon/desktop entry points, initializes a first-run policy, and never enables observation or downloads/launches a model automatically.

The first-run policy explains metadata-only observation, excluded capture classes, detected applications, provider capabilities, disabled permissions, pause/emergency controls, local data location, and history deletion. MLLminal resolves abstract capabilities through native applications, the signed-in browser bridge, bundled inspection, optional portable providers, or manual handoff. It never requires Excel or classic Outlook. Startup-at-login is opt-in through `install.ps1 -EnableStartup`. Uninstall retains local history by default; `uninstall.ps1 -DeleteData` explicitly removes it. `export-diagnostics.ps1` excludes tokens, databases, and credentials.

Hardware recommendations are available with `mllminal system hardware` and the authenticated daemon endpoint `/v1/system/hardware`. Profiles are Light, Standard, and High capability. A profile never starts a model or downloads dependencies without confirmation.

install.ps1 writes provider-inventory.json after detecting Excel, classic/modern Outlook, LibreOffice, and browser-bridge status. Optional LibreOffice is not silently downloaded: the installer explains that the approximately 350 MB component provides portable spreadsheet PDF rendering, asks for consent, and permits skipping it. Lightweight mode skips optional components and keeps bundled Python workbook inspection plus manual handoffs.
