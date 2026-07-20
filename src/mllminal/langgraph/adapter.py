"""Translate typed workflows to an optional LangGraph-compatible specification."""

from importlib.util import find_spec

from mllminal.langgraph.contracts import LangGraphEdge, LangGraphNode, LangGraphWorkflowSpec
from mllminal.workflow.contracts import WorkflowDefinition


class LangGraphWorkflowAdapter:
    def available(self) -> bool:
        return find_spec("langgraph") is not None

    def spec(self, definition: WorkflowDefinition) -> LangGraphWorkflowSpec:
        nodes = [
            LangGraphNode(
                id=step.id,
                capability=step.capability,
                order=step.order,
                approval_required=step.approval_required,
            )
            for step in definition.steps
        ]
        edges = [
            LangGraphEdge(source=source.id, target=target.id)
            for source, target in zip(definition.steps, definition.steps[1:], strict=False)
        ]
        return LangGraphWorkflowSpec(
            workflow_id=definition.id,
            name=definition.name,
            nodes=nodes,
            edges=edges,
            entrypoint=nodes[0].id,
            terminal=nodes[-1].id,
        )
