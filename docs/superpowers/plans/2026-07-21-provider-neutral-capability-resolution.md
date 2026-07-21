# Provider-Neutral Capability Resolution Implementation Plan

> For agentic workers: use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

Goal: Replace application-specific spreadsheet/email requirements with deterministic provider resolution and portable, honest fallbacks.

Architecture: Abstract capability contracts are resolved by a local provider registry. Each provider reports capabilities, permissions, consequence class, availability, and verification strength. The runtime persists the selected provider and returns manual or deferred outcomes when no safe provider exists.

Tech Stack: Python 3.12, Pydantic, FastAPI, Typer, SQLAlchemy, Windows COM/UIA when available, browser bridge contracts, PowerShell installer scripts.

## Global Constraints

- Preserve current missing Excel/classic-Outlook evidence as provider-specific deferred acceptance.
- Do not require Excel COM, OUTLOOK.EXE, classic Outlook, or Microsoft Office for installation.
- Use abstract capabilities: spreadsheet.inspect, spreadsheet.export_pdf, email.create_draft.
- Never extract cookies, tokens, passwords, authentication headers, or saved credentials.
- Never expose automatic email send.
- Do not silently install large dependencies; show size, reason, consent, skip, and lightweight mode.
- Do not claim an inspection library can reproduce Excel-quality PDF rendering.
- Keep local-only data guarantees and independent verification.

### Task 1: Define provider-neutral contracts

Files:
- Create src/mllminal/providers/contracts.py
- Create src/mllminal/providers/registry.py
- Modify src/mllminal/apps/contracts.py only for compatibility aliases
- Modify src/mllminal/providers/__init__.py

Interfaces:
- AbstractCapability includes spreadsheet.inspect, spreadsheet.export_pdf, email.create_draft, email.set_recipients, email.set_subject, email.set_body, email.attach_file, and email.verify_draft.
- ProviderKind includes native, browser, bundled, portable, manual, unsupported.
- ProviderAvailability reports provider, detected, available, capabilities, permissions, consequence classes, verification strength, version, install state, and explanation.
- ResolvedCapability reports abstract capability, provider, operation, and fallback rank.
- ProviderAdapter exposes detect(), capabilities(), execute(), and verify().

Steps:
- [ ] Add Pydantic contracts with stable JSON values and compatibility aliases.
- [ ] Make unsupported capability resolution a structured result rather than an exception.
- [ ] Keep consequence classes limited to read-only, reversible, and draft-only external effects.

### Task 2: Implement deterministic resolver and registry

Files:
- Create src/mllminal/providers/resolver.py
- Modify src/mllminal/apps/service.py
- Modify src/mllminal/daemon/api.py
- Modify src/mllminal/cli/main.py

Interfaces:
- CapabilityResolver.resolve(capability: str, preferred_provider: str | None = None) -> CapabilityResolution.
- CapabilityResolver.discover() -> list[ProviderAvailability].
- API routes GET /v1/providers and POST /v1/capabilities/resolve.
- CLI commands mllminal providers list and mllminal capability resolve payload.

Steps:
- [ ] Register providers in deterministic native, browser, bundled, portable, manual, unsupported order.
- [ ] Persist selected provider and reason in audit output.
- [ ] Return manual_required when only manual handoff is available.
- [ ] Return unsupported with a clear explanation when no provider exists.

### Task 3: Adapt existing desktop providers

Files:
- Create src/mllminal/providers/native.py
- Modify src/mllminal/apps/adapters.py
- Modify src/mllminal/apps/service.py

Steps:
- [ ] Advertise Excel COM as optional excel.desktop for abstract spreadsheet capabilities.
- [ ] Advertise Outlook COM as optional outlook.classic for abstract email capabilities.
- [ ] Preserve read-only Excel, link suppression, macro identification, output verification, and close-on-failure.
- [ ] Preserve draft-only Outlook and no-send behavior.
- [ ] Make missing binaries normal unavailable-provider results.
- [ ] Keep old application-specific aliases for backward compatibility.

### Task 4: Add portable spreadsheet providers

Files:
- Create src/mllminal/providers/spreadsheets.py
- Modify src/mllminal/config.py
- Modify pyproject.toml only for optional dependency groups
- Modify packaging/windows/install.ps1
- Modify packaging/windows/MLLminal.iss

Steps:
- [ ] Discover soffice.exe through PATH and standard Windows locations.
- [ ] Implement read-only workbook inspection without Excel.
- [ ] Implement LibreOffice preview/export with approved paths and independent verification.
- [ ] Return manual handoff for spreadsheet.export_pdf when only Python inspection is available.
- [ ] Add provider inventory with dependency size, reason, consent, skip, and lightweight mode.
- [ ] Never silently download or launch a large provider.

### Task 5: Add email fallback providers

Files:
- Create src/mllminal/providers/email.py
- Modify src/mllminal/apps/browser_bridge.py
- Modify src/mllminal/apps/adapters.py
- Modify src/mllminal/apps/service.py

Steps:
- [ ] Detect modern Outlook and report installed-but-unautomatable status honestly.
- [ ] Add browser email provider using a granted domain and semantic DOM bridge.
- [ ] Add system mail compose as visible manual_required draft handoff.
- [ ] Add domain-specific grants and origin checks.
- [ ] Block authentication, payment, account-security, and secure-input pages.
- [ ] Keep cookies, tokens, passwords, and headers opaque.
- [ ] Independently verify drafts where a read surface exists; otherwise report manual verification.
- [ ] Omit email.send from every provider.

### Task 6: Make compiler, repair, and acceptance provider-neutral

Files:
- Modify src/mllminal/compiler/service.py
- Modify src/mllminal/compiler/contracts.py
- Modify src/mllminal/repair/service.py
- Modify src/mllminal/acceptance/service.py

Steps:
- [ ] Map legacy excel.* and email.* names to abstract names during compilation.
- [ ] Preserve provider-neutral workflow JSON across provider changes.
- [ ] Include provider resolution in permission and verification manifests.
- [ ] Add selected-provider and fallback evidence to acceptance reports.
- [ ] Keep Excel/classic-Outlook rows deferred only, not global blockers.

### Task 7: Add browser extension and native bridge contracts

Files:
- Modify src/mllminal/apps/browser_bridge.py
- Create packaging/browser-extension/manifest.json
- Create packaging/browser-extension/background.js
- Create packaging/browser-extension/content.js
- Create packaging/browser-extension/README.md
- Create packaging/browser-bridge/README.md

Steps:
- [ ] Version native bridge messages with origin, domain, capability, request_id, and payload.
- [ ] Expose semantic DOM controls only after domain grant.
- [ ] Use loopback authentication and never return cookies or tokens.
- [ ] Add visible active indicator and revoke path.
- [ ] Block secure/auth/payment/account-security pages.
- [ ] Reject origin spoofing, duplicate requests, malformed messages, and replay.
- [ ] Document browser installation, consent, lightweight mode, and no-cloud behavior.

### Task 8: Update installer and evidence

Files:
- Modify packaging/windows/README.md
- Modify packaging/windows/install.ps1
- Modify docs/productization/acceptance-results.md
- Modify docs/productization/security-model.md
- Modify docs/productization/performance-baseline.md
- Modify docs/productization/windows-product-acceptance.md

Steps:
- [ ] Replace application-required language with provider discovery and capability inventory.
- [ ] Record Excel/classic-Outlook as deferred providers; assess modern Outlook, browser, portable, and manual rows separately.
- [ ] Add capability-level acceptance for inspection, output generation, draft preparation, provider selection, degradation, and credential suppression.
- [ ] Add browser origin spoofing and provider handoff security cases.
- [ ] Add provider discovery, fallback selection, and dependency load metrics.

### Task 9: Remote verification and publication

Steps:
- [ ] Apply formatter to affected Python files.
- [ ] Run static checks only; do not run the local test suite.
- [ ] Stage only provider-resolution files.
- [ ] Commit with message: add provider-neutral capability resolution.
- [ ] Push Israelobuk/mllminal-provider-resolution.
- [ ] Open a draft PR, wait for remote CI, fix only scoped failures, mark ready, and merge when green.
- [ ] Preserve deferred provider evidence in the merged acceptance report.
