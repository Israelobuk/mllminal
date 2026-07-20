# Workflow compiler and variable inference

Milestone 7 turns repeated mined candidates into an inactive typed workflow draft. The compiler is deterministic and local: it does not activate, execute, send, or grant permissions.

## Output

`POST /v1/workflow-compiler/compile` and `mllminal workflow compile` accept repeated mined candidates and return:

- a `WorkflowDefinition` draft with contiguous typed steps;
- variable types including file, folder, date, datetime, contact, application, selected item, previous output, and user choice;
- confidence and evidence references for each inferred variable;
- stable-structure confidence;
- a permission manifest with approval requirements;
- verification and rollback manifests;
- unsupported-step reports and explicit user questions.

Repeated ISO-date filename patterns such as `report-2026-07-06.xlsx`, `report-2026-07-13.xlsx`, and `report-2026-07-20.xlsx` infer a reviewable `reporting_date` input and preserve the filename template. Repeated differing file-operation values infer a `source_file` input. Stable repeated values remain constants; the compiler does not turn changing folders into wildcards without evidence.

Email mappings stop at `email.create_draft`; there is no send capability. Consequential filesystem, Excel, and email steps require explicit approval in the generated draft. Unsupported observations remain visible as unsupported placeholders so the user must choose a bounded adapter before activation.

## Acceptance

Provide three mined demonstrations of the same weekly-report process. Confirm that one draft candidate contains a date variable, source-file variable, stable destination folder, reviewable draft-recipient question, explicit approval before draft creation, no send capability, and independent verification requirements. Keep the prior demonstrations and candidate evidence available for review; compilation does not mutate them.
