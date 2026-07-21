# Optional Excel desktop provider

The Excel COM adapter is one optional native provider behind the abstract spreadsheet capabilities. MLLminal does not require Excel; provider resolution can use browser, bundled inspection, LibreOffice, or manual handoff. It does not request Microsoft developer keys or extract passwords, cookies, session tokens, or credentials.

## Safety boundary

Workbooks open read-only with external links disabled (`UpdateLinks=0`), `AddToMru` disabled, alerts disabled, and macros identified without executing them. Macro-enabled extensions are returned in metadata and remain visibly marked. Original files are never overwritten by the adapter. Save-copy and PDF output paths must be inside the configured workspace root, have an existing parent, and reject collisions.

The legacy adapter retains its application-scoped surface for compatibility, while the workflow runtime requests spreadsheet.inspect, spreadsheet.export_pdf, and spreadsheet.verify_output. Mutating output operations remain preview-only until workflow authorization and provider-specific approval are present.

## Acceptance

If Excel is installed, place a non-sensitive test workbook in an approved root. Detect Excel, open the workbook, list sheets, select the configured sheet, export it to a new PDF, verify that the PDF exists and is non-empty, and close the workbook without saving. Confirm the original workbook hash is unchanged and the audit file records the operation sequence.

Excel-specific acceptance is optional provider evidence. The current machine has no real Excel acceptance result; that case remains deferred. Capability-level acceptance must use an available provider and must not claim Excel-quality rendering from the bundled inspector.
