# Provider-neutral capability resolution

MLLminal workflows request capabilities, not named desktop applications. The runtime resolves each request in this order:

1. native installed application;
2. signed-in browser surface through the browser bridge;
3. bundled local provider;
4. optional portable open-source provider;
5. explicit manual handoff;
6. unsupported with a reason and remediation.

The selected provider and its verification strength are returned by discovery and resolution APIs and are included in workflow evidence. Users can skip optional providers and continue in lightweight mode.

## Spreadsheet capabilities

spreadsheet.inspect can use the bundled OOXML inspector and reports workbook metadata, sheets, hashes, macro presence, and external-link presence. It does not evaluate formulas or claim Excel-quality rendering.

spreadsheet.export_pdf uses Excel only when its adapter is available, then a connected browser surface, then LibreOffice when installed, and otherwise returns a manual export handoff. The system never presents openpyxl or the bundled inspector as an Excel PDF renderer.

## Email capabilities

email.create_draft is draft-only. Providers include classic Outlook when available, modern Outlook UI Automation when an active surface exists, Gmail or Outlook Web through the browser bridge, and a system mailto handoff. No provider has a send capability.

## Browser safety

The extension and native seam use semantic controls and domain-specific grants. They do not extract cookies, tokens, passwords, or page secrets. Authentication, payment, and account-security paths are blocked. A visible MLLminal active indicator is shown while the extension is active.
