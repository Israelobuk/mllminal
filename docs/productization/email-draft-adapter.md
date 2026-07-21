# Optional Outlook desktop draft provider

The Outlook COM adapter is one optional native provider behind the abstract email.create_draft capability. MLLminal does not require classic Outlook; modern Outlook UI Automation, signed-in browser surfaces, local mail clients, and system compose handoff are supported fallback paths. It does not read passwords, cookies, session tokens, refresh tokens, authentication headers, or saved credentials, and it has no send capability.

## Capabilities and permissions

The legacy adapter retains its application-scoped surface for compatibility. The provider-neutral runtime requests email.create_draft and related draft fields. All modifying capabilities use the granular email.draft permission.

Draft creation and edits remain preview-only until the existing application bridge workflow authorization, action approval, and grant are present. Attachments must be existing files under the approved workspace root and cannot escape through traversal or symlinks. The draft remains unsent for user review. Every operation is audit logged.

## Acceptance

If classic Outlook is installed with a signed-in profile, locate the exported weekly-report PDF under an approved root, create a draft, set recipients, populate subject and plain-text body, attach the PDF, verify that the draft is saved and unsent, and stop. Confirm Outlook presents the draft for review and no send action is exposed or performed.

Classic-Outlook-specific acceptance is optional provider evidence. The current machine has no real classic Outlook acceptance result; that case remains deferred. Browser and manual draft paths remain valid and sending is never exposed.
