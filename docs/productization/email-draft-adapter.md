# Real Outlook email draft adapter

Milestone 6 supports one real local path: Outlook desktop through its signed-in COM application surface. It does not read passwords, cookies, session tokens, refresh tokens, authentication headers, or saved credentials, and it has no send capability.

## Capabilities and permissions

The adapter exposes `email.detect_client`, `create_draft`, `set_recipients`, `set_subject`, `set_body`, `attach_file`, and `verify_draft`. All modifying capabilities use the granular `email.draft` permission. Send, delete-message, account-settings, and credential capabilities are intentionally absent.

Draft creation and edits remain preview-only until the existing application bridge workflow authorization, action approval, and grant are present. Attachments must be existing files under the approved workspace root and cannot escape through traversal or symlinks. The draft remains unsent for user review. Every operation is audit logged.

## Acceptance

On a real Windows machine with a signed-in Outlook desktop profile, locate the exported weekly-report PDF under an approved root, create a draft, set recipients, populate subject and plain-text body, attach the PDF, verify that the draft is saved and unsent, and stop. Confirm Outlook presents the draft for review and no send action is exposed or performed.

CI verifies contracts and unavailable-client behavior on the hosted runner. Manual acceptance remains required for the signed-in Outlook surface, draft folder persistence, attachment rendering, and user review.
