# Adaptive workflow suggestions and preference learning

MLLminal may mine repeated semantic interaction patterns into durable, ranked workflow suggestions. Suggestions are advisory only: they never execute a workflow, grant a permission, approve an action, or promote a policy.

Ranking is deterministic. The score records occurrence frequency, mined confidence, independent-verification availability, explicit preference scope, and a bounded rejection penalty. The service stores its ranking components and a human-readable explanation with each suggestion. Identical candidate evidence is persisted idempotently; new evidence can be ranked again after feedback.

Preferences are explicit and scoped in descending precedence: workflow candidate, application, then global. A disabled preference keeps a suggestion pending. Feedback is recorded with a caller-provided idempotency key, so retried accept/reject/dismiss/snooze/disable requests do not create duplicate learning records.

Emergency stop always wins. Missing independent verification, an active emergency stop, or a disabling preference prevents eligibility. Suggestions preserve the existing workflow approval and permission paths. Adaptations are draft proposals requiring explicit review and are never automatically promoted.

The authenticated daemon exposes `GET /v1/suggestions`, `POST /v1/suggestions/propose`, feedback and adaptation routes below `/v1/suggestions/{id}`, and `GET`/`PUT /v1/suggestion-preferences`. The terminal equivalents are `mllminal suggestions` and `mllminal preferences`. The desktop client presents daemon-owned counts only; it does not own or execute suggestion state.

Suggestion, feedback, preference, ranking-decision, and adaptation-proposal records contain metadata and structural evidence only. Learning persistence rejects secret and secure-field names such as passwords, tokens, messages, tool arguments, typed text, and cookies.