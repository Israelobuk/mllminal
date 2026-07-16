"""Replaceable Mil provider and deterministic foundation implementation."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from mllminal.contracts import Plan, PlanStep, RiskLevel, ToolProposal


@dataclass(frozen=True)
class ProviderResponse:
    chunks: tuple[str, ...]
    plan: Plan


class MilProvider(Protocol):
    def plan(self, task_id: str, request: str, workspace: Path) -> ProviderResponse: ...


class DeterministicMilProvider:
    def plan(self, task_id: str, request: str, workspace: Path) -> ProviderResponse:
        del workspace
        prefix = "I can inspect" if "inspect" in request.casefold() else "I will inspect"
        proposal = ToolProposal(
            tool_name="project.inspect_metadata",
            arguments={},
            risk=RiskLevel.LOW,
            required_permission="filesystem.read",
            reversible=True,
            verifier="verify_project_metadata",
        )
        return ProviderResponse(
            chunks=(
                f"{prefix} the attached project using a read-only typed tool. ",
                "Approval is required before execution.",
            ),
            plan=Plan(
                task_id=task_id,
                steps=[PlanStep(position=1, title="Inspect project metadata", proposal=proposal)],
            ),
        )
