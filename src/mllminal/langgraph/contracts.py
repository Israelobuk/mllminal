"""Provider-neutral graph specifications for typed workflow definitions."""

from pydantic import Field

from mllminal.contracts import Contract


class LangGraphNode(Contract):
    id: str
    capability: str
    order: int = Field(ge=1)
    approval_required: bool = True


class LangGraphEdge(Contract):
    source: str
    target: str


class LangGraphWorkflowSpec(Contract):
    workflow_id: str
    name: str
    nodes: list[LangGraphNode] = Field(min_length=1)
    edges: list[LangGraphEdge] = Field(default_factory=list)
    entrypoint: str
    terminal: str
    optional_dependency: str = "langgraph"
