# Provider-Neutral Capability Resolution Design

## Goal

MLLminal resolves workflow capabilities through safe providers available on the user device instead of requiring Excel COM, classic Outlook, or any single desktop application. Existing missing-application evidence remains preserved as deferred provider-specific acceptance, while capability-level acceptance becomes the product completion gate.

## Architecture

Workflow definitions use abstract capability names such as spreadsheet.inspect, spreadsheet.export_pdf, and email.create_draft. A provider registry discovers local providers and returns availability, supported operations, consequence class, permission scope, and evidence requirements. A resolver selects the first safe provider that supports the requested operation:

1. native installed application
2. browser-based application through the local browser bridge
3. bundled local provider
4. approved portable open-source provider
5. manual handoff
6. explicit unsupported result

The resolver is deterministic, visible, and persisted with each execution. A workflow stores the abstract capability and selected provider metadata, never an application-specific implementation requirement.

## Provider boundaries

- Excel COM remains an optional excel.desktop provider.
- LibreOffice headless is an optional libreoffice.headless provider when the executable is already installed or the user explicitly consents to an approved package.
- Python workbook inspection is a read-only spreadsheet.python_inspection provider. It may inspect workbook structure but never claims Excel-quality rendering.
- Browser spreadsheets are exposed through a domain-authorized browser provider.
- Outlook COM remains an optional outlook.classic provider.
- Modern Outlook and Gmail/Outlook Web use browser or UI Automation providers without extracting cookies, tokens, passwords, or authentication headers.
- System mail compose is a draft handoff only; it never reports independent draft verification.
- Manual handoff is a first-class provider result with visible operator instructions and no automatic side effect.

## Data flow and security

User or Mil proposes an abstract capability. The runtime validates the capability and consequence class, asks the resolver for a provider, displays the provider and permissions, previews the operation, requires approval for writes or drafts, executes through the selected adapter, and independently verifies the result. A missing provider produces a structured deferred or manual_required result, not an import error or silent fallback.

Provider discovery is local and metadata-only. Browser providers use domain-specific grants and semantic DOM controls; content is never sent to an MLLminal cloud service. Authentication surfaces, payment pages, account-security pages, and secure fields are blocked. Dependencies are never silently downloaded. Installer UI exposes provider name, capability list, version, download size, reason, consent state, and lightweight-mode behavior.

All draft-capable email providers expose draft-only operations. No provider exposes email.send. Each mutation retains idempotency, audit, preview, approval, independent verification, and emergency-stop checks.

## Acceptance model

Global acceptance proves that the resolver can inspect a real spreadsheet through one available provider and prepare an email draft through one available provider, with automatic visible provider selection and graceful unavailable-provider behavior. Excel-specific and classic-Outlook-specific tests are provider-specific acceptance rows and remain deferred on the current machine. Acceptance evidence must include the selected provider, capabilities, fallback path, permissions, verification result, and no-credential-extraction assertion.

## Scope

This slice changes provider contracts, resolution, portable discovery, browser/manual handoff contracts, workflow capability names, installer provider visibility, acceptance reporting, and documentation. It does not silently install dependencies, add automatic email sending, or claim a portable provider can reproduce Excel rendering without evidence.
