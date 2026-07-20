# Windows packaging

## What is real

packaging/windows/MLLminal.iss contains an Inno Setup installer definition. install.ps1 creates a private environment, installs the wheel and entry points, initializes first-run policy, and can add startup-at-login only when explicitly requested. uninstall.ps1 retains data by default and supports explicit deletion. export-diagnostics.ps1 excludes tokens, databases, and credentials.

Observation remains disabled after installation. First-run policy explains observation, excluded data, applications, permissions, pause, emergency stop, local storage, and history deletion. Hardware detection is exposed through mllminal system hardware and the daemon hardware endpoint.

## Simulated, unsupported, and boundaries

The repository contains installer sources, not a signed installer artifact. CI does not compile Inno Setup, perform a clean install, launch the installed daemon, or verify uninstall retention. The installer never downloads or launches a heavy model automatically, grants application permissions, enables observation, or creates an email-send capability. Data deletion requires an explicit choice and diagnostics omit authentication tokens, database contents, credentials, and session material.

## Manual test procedure

1. Build a wheel and place it in packaging/windows/dist.
2. Compile Inno Setup on a clean Windows account.
3. Install without startup; verify observation is off and the local data path is shown.
4. Verify CLI, daemon, and mllminal-ui launch from the installed environment.
5. Reinstall with startup enabled and confirm only the daemon starts at login.
6. Export diagnostics and inspect that secrets and database content are absent.
7. Uninstall without DeleteData and verify history remains.
8. Uninstall with DeleteData and verify the documented data directory is removed.

## Automated coverage and next work

Remote CI validates Python packaging metadata and static checks. Inno compilation, clean installation, startup behavior, and deletion semantics remain manual-required. Produce a signed installer artifact before classifying packaging as production-capable.
