# Adaptive execution policy

Adaptive execution is an advisory, deterministic layer inside the existing typed workflow runtime. Before a step with an application profile runs, it safety-filters its registered backend candidates, records the evidence used for ranking, and chooses only the highest-ranked eligible backend. Emergency stop rejects every candidate before any handler runs.

The persisted `AdaptiveExecutionDecision` includes the selected and rejected backends, reliability snapshot, safety filters, policy version, explanation, execution outcome, verification outcome, and reward provenance. The existing profile service updates backend reliability only after execution and independent workflow verification.

The CLI (`mllminal adaptive ...`) and authenticated `/v1/adaptive/...` endpoints read the same durable records. Candidate policy evaluation remains explicitly offline and advisory; no policy is promoted automatically.

## Validation boundary

The automated tests use bounded in-process handlers to simulate a failed Windows UI Automation target followed by a verified vision fallback, durable restart behavior, clarification-safe target handling, and emergency-stop suppression. They do not claim live control of a desktop application. Live application acceptance still requires a user-approved, available local application and its independent verifier.
