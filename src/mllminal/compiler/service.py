"""Deterministic compiler from repeated mined candidates to draft workflows."""

from __future__ import annotations

import re
from typing import Any

from mllminal.compiler.contracts import (
    CompilationResult,
    CompilerRequest,
    EvidenceReference,
    InferredVariable,
    PermissionManifestEntry,
    UnsupportedStepReport,
)
from mllminal.mining.contracts import MinedStep
from mllminal.mining.contracts import WorkflowCandidate as MinedWorkflowCandidate
from mllminal.workflow.contracts import (
    WorkflowDefinition,
    WorkflowInput,
    WorkflowInputType,
    WorkflowPermission,
    WorkflowStep,
    WorkflowVerification,
)

_DATE_VALUE = re.compile(r"^(?P<prefix>.*?)(?P<date>\d{4}-\d{2}-\d{2})(?P<suffix>.*)$")
_CAPABILITY_ACTIONS = {
    "rename": "filesystem.rename",
    "move": "filesystem.move",
    "copy": "filesystem.copy",
    "delete": "filesystem.delete_to_recycle_bin",
    "create_folder": "filesystem.create_folder",
}


class WorkflowCompilerService:
    """Compile only observed repeated structure; never activate or execute a workflow."""

    def compile(self, request: CompilerRequest) -> CompilationResult:
        candidates = request.candidates
        structure_confidence = self._structure_confidence(candidates)
        reference = candidates[0]
        inferred, constants, evidence = self._infer_variables(candidates)
        steps: list[WorkflowStep] = []
        unsupported: list[UnsupportedStepReport] = []
        permissions: dict[str, PermissionManifestEntry] = {}
        verification: list[str] = []
        for index, mined_step in enumerate(reference.steps):
            capability = self._capability(mined_step)
            if capability is None:
                unsupported.append(
                    UnsupportedStepReport(
                        step_index=index,
                        kind=mined_step.kind,
                        application=mined_step.application,
                        reason="No bounded capability mapping is available for this observed step",
                        source_candidate_ids=[candidate.id for candidate in candidates],
                    )
                )
                capability = f"unsupported.{mined_step.kind}"
            consequential = capability.startswith(
                ("filesystem.", "spreadsheet.", "email.")
            ) and capability not in {
                "filesystem.list",
                "filesystem.inspect",
                "filesystem.find_latest",
                "filesystem.exists",
                "filesystem.hash",
                "spreadsheet.inspect",
                "spreadsheet.verify_output",
                "email.detect_client",
                "email.verify_draft",
            }
            approval_required = consequential
            arguments = self._arguments(capability, inferred, constants, index)
            rollback = (
                "filesystem.restore"
                if capability.startswith("filesystem.")
                and capability
                not in {
                    "filesystem.list",
                    "filesystem.inspect",
                    "filesystem.find_latest",
                    "filesystem.exists",
                    "filesystem.hash",
                }
                else None
            )
            steps.append(
                WorkflowStep(
                    order=index + 1,
                    capability=capability,
                    arguments=arguments,
                    approval_required=approval_required,
                    rollback_capability=rollback,
                    verification=WorkflowVerification(
                        expected={"operation": capability.rsplit(".", 1)[-1]}
                    ),
                )
            )
            permission = self._permission(capability, consequential, approval_required)
            if permission is not None:
                permissions[capability] = permission
            verification.append(self._verification(capability))
        inputs = [WorkflowInput(name=item.name, type=item.type, required=True) for item in inferred]
        workflow = WorkflowDefinition(
            name=request.name,
            inputs=inputs,
            permissions=[
                WorkflowPermission(
                    capability=item.capability,
                    scope=item.scope,
                    consequential=item.consequential,
                )
                for item in permissions.values()
            ]
            + [
                WorkflowPermission(
                    capability=step.capability,
                    scope="workflow.unsupported",
                    consequential=True,
                )
                for step in steps
                if step.capability.startswith("unsupported.")
            ],
            steps=steps,
        )
        questions = self._questions(inferred, unsupported, candidates)
        return CompilationResult(
            workflow=workflow,
            structure_confidence=structure_confidence,
            inferred_variables=inferred,
            evidence_references=evidence,
            unsupported_steps=unsupported,
            permission_manifest=list(permissions.values()),
            verification_manifest=verification,
            user_questions=questions,
            source_candidate_ids=[candidate.id for candidate in candidates],
        )

    @staticmethod
    def _structure_confidence(candidates: list[MinedWorkflowCandidate]) -> float:
        if len(candidates) < 2:
            return 0.35
        first = [(step.kind, step.application, step.action_type) for step in candidates[0].steps]
        matching = sum(
            [(step.kind, step.application, step.action_type) for step in candidate.steps] == first
            for candidate in candidates[1:]
        )
        return round(min(1.0, 0.5 + 0.5 * matching / max(1, len(candidates) - 1)), 3)

    def _infer_variables(
        self, candidates: list[MinedWorkflowCandidate]
    ) -> tuple[list[InferredVariable], dict[int, str], list[EvidenceReference]]:
        variables: list[InferredVariable] = []
        constants: dict[int, str] = {}
        evidence: list[EvidenceReference] = []
        max_steps = min(len(candidate.steps) for candidate in candidates)
        used_names: set[str] = set()
        for index in range(max_steps):
            values = [candidate.steps[index].control_name for candidate in candidates]
            observed = [value for value in values if value]
            if not observed:
                continue
            refs = [
                EvidenceReference(
                    candidate_id=candidate.id,
                    step_index=index,
                    observed_values=[candidate.steps[index].control_name or ""],
                    explanation="Observed at the same repeated workflow position",
                )
                for candidate in candidates
            ]
            evidence.extend(refs)
            if len(set(observed)) == 1:
                constants[index] = observed[0]
                continue
            date_matches = [_DATE_VALUE.match(value) for value in observed]
            if all(match is not None for match in date_matches):
                prefixes = {match.group("prefix") for match in date_matches if match}
                suffixes = {match.group("suffix") for match in date_matches if match}
                if len(prefixes) == 1 and len(suffixes) == 1:
                    name = self._unique_name("reporting_date", used_names)
                    template = f"{next(iter(prefixes))}${{{name}}}{next(iter(suffixes))}"
                    variables.append(
                        InferredVariable(
                            name=name,
                            type=WorkflowInputType.DATE,
                            confidence=0.92,
                            template=template,
                            evidence=refs,
                        )
                    )
                    continue
            if candidates[0].steps[index].kind == "file.operation":
                name = self._unique_name("source_file", used_names)
                variables.append(
                    InferredVariable(
                        name=name,
                        type=WorkflowInputType.FILE,
                        confidence=0.72,
                        evidence=refs,
                    )
                )
        return variables, constants, evidence

    @staticmethod
    def _unique_name(base: str, used: set[str]) -> str:
        name = base
        index = 2
        while name in used:
            name = f"{base}_{index}"
            index += 1
        used.add(name)
        return name

    @staticmethod
    def _capability(step: MinedStep) -> str | None:
        action = (step.action_type or "").casefold().replace(" ", "_")
        if step.kind == "file.operation":
            for key, capability in _CAPABILITY_ACTIONS.items():
                if key in action:
                    return capability
        if step.kind == "control.invoked":
            if step.application.casefold() == "excel" and "export" in action:
                return "spreadsheet.export_pdf"
            if step.application.casefold() in {"email", "outlook"} and "draft" in action:
                return "email.create_draft"
        return None

    @staticmethod
    def _arguments(
        capability: str,
        inferred: list[InferredVariable],
        constants: dict[int, str],
        index: int,
    ) -> dict[str, Any]:
        names = {item.name: item for item in inferred}
        if capability in {"filesystem.rename", "filesystem.move", "filesystem.copy"}:
            result: dict[str, Any] = (
                {"source": "$input.source_file"} if "source_file" in names else {}
            )
            if "reporting_date" in names:
                result["destination_name"] = names["reporting_date"].template
            elif index in constants:
                result["destination_name"] = constants[index]
            return result
        if capability == "filesystem.create_folder" and index in constants:
            return {"path": constants[index]}
        return {}

    @staticmethod
    def _permission(
        capability: str, consequential: bool, approval_required: bool
    ) -> PermissionManifestEntry | None:
        if capability.startswith("filesystem."):
            scope = "filesystem.write" if consequential else "filesystem.read"
        elif capability.startswith("spreadsheet."):
            scope = "spreadsheet.export" if consequential else "spreadsheet.read"
        elif capability.startswith("email."):
            scope = "email.draft"
        else:
            return None
        return PermissionManifestEntry(
            capability=capability,
            scope=scope,
            consequential=consequential,
            approval_required=approval_required,
        )

    @staticmethod
    def _verification(capability: str) -> str:
        if capability in {"filesystem.rename", "filesystem.move"}:
            return "Verify destination exists and source is absent"
        if capability == "filesystem.copy":
            return "Verify destination exists and optional hash matches"
        if capability == "spreadsheet.export_pdf":
            return "Verify PDF exists and is non-empty"
        if capability == "email.create_draft":
            return "Verify draft exists and remains unsent"
        if capability.startswith("unsupported."):
            return "Unavailable until a bounded adapter is selected"
        return "Verify capability output independently"

    @staticmethod
    def _questions(
        inferred: list[InferredVariable],
        unsupported: list[UnsupportedStepReport],
        candidates: list[MinedWorkflowCandidate],
    ) -> list[str]:
        questions = [
            f"Confirm the value and source for workflow input '{item.name}'."
            for item in inferred
            if item.type
            in {WorkflowInputType.FILE, WorkflowInputType.CONTACT, WorkflowInputType.USER_CHOICE}
        ]
        if any(item.name == "reporting_date" for item in inferred):
            questions.append("Confirm the reporting date format and timezone before each run.")
        if any(
            step.kind == "control.invoked" and "email" in step.application.casefold()
            for step in candidates[0].steps
        ):
            questions.append(
                "Review draft recipients before creating the email draft; sending is unavailable."
            )
        if unsupported:
            questions.append(
                "Review unsupported steps and select a bounded capability before activation."
            )
        if len(candidates) < 3:
            questions.append(
                "Provide at least three demonstrations before treating inferred "
                "structure as stable."
            )
        return questions
