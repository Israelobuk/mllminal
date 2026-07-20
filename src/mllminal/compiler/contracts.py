"""Contracts for deterministic workflow compilation and inference."""

from pydantic import Field

from mllminal.contracts import Contract, new_id
from mllminal.mining.contracts import WorkflowCandidate as MinedWorkflowCandidate
from mllminal.workflow.contracts import WorkflowDefinition, WorkflowInputType


class CompilerRequest(Contract):
    name: str = Field(min_length=1, max_length=128)
    candidates: list[MinedWorkflowCandidate] = Field(min_length=1, max_length=32)


class EvidenceReference(Contract):
    id: str = Field(default_factory=new_id)
    candidate_id: str
    step_index: int = Field(ge=0)
    observed_values: list[str] = Field(default_factory=list)
    explanation: str


class InferredVariable(Contract):
    name: str
    type: WorkflowInputType
    confidence: float = Field(ge=0, le=1)
    template: str | None = None
    evidence: list[EvidenceReference] = Field(default_factory=list)


class UnsupportedStepReport(Contract):
    step_index: int = Field(ge=0)
    kind: str
    application: str
    reason: str
    source_candidate_ids: list[str] = Field(default_factory=list)


class PermissionManifestEntry(Contract):
    capability: str
    scope: str
    consequential: bool
    approval_required: bool


class CompilationResult(Contract):
    workflow: WorkflowDefinition
    structure_confidence: float = Field(ge=0, le=1)
    inferred_variables: list[InferredVariable] = Field(default_factory=list)
    evidence_references: list[EvidenceReference] = Field(default_factory=list)
    unsupported_steps: list[UnsupportedStepReport] = Field(default_factory=list)
    permission_manifest: list[PermissionManifestEntry] = Field(default_factory=list)
    verification_manifest: list[str] = Field(default_factory=list)
    user_questions: list[str] = Field(default_factory=list)
    source_candidate_ids: list[str] = Field(default_factory=list)
