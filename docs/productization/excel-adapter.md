# Real Excel desktop adapter

Milestone 5 uses one real local path: Excel COM through the already installed desktop application. It does not request Microsoft developer keys or extract passwords, cookies, session tokens, or credentials.

## Safety boundary

Workbooks open read-only with external links disabled (`UpdateLinks=0`), `AddToMru` disabled, alerts disabled, and macros identified without executing them. Macro-enabled extensions are returned in metadata and remain visibly marked. Original files are never overwritten by the adapter. Save-copy and PDF output paths must be inside the configured workspace root, have an existing parent, and reject collisions.

The adapter exposes `excel.detect`, `open_workbook`, `list_sheets`, `inspect_metadata`, `select_sheet`, `save_copy`, `export_pdf`, `close_workbook`, and `verify_output`. Mutating output operations remain preview-only until the existing workflow authorization, action approval, and `excel.write` grant are present. Each operation is audit logged. Any COM failure closes the affected workbook and quits the private Excel instance so the daemon does not retain an unknown automation state.

## Acceptance

On a real Windows machine with Excel installed, place a non-sensitive test workbook in an approved root. Detect Excel, open the workbook, list sheets, select the configured sheet, export it to a new PDF, verify that the PDF exists and is non-empty, and close the workbook without saving. Confirm the original workbook hash is unchanged and the audit file records the operation sequence.

CI verifies provider-neutral contracts and unavailable-provider behavior on the hosted runner. Manual acceptance remains required for installed Excel COM, macro/link safety, workbook cleanup, and PDF rendering.
