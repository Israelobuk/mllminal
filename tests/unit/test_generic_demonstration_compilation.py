from mllminal.demonstration.service import DemonstrationService
from mllminal.interaction.contracts import (
    InteractionEvent,
    InteractionKind,
    SemanticTarget,
)


def test_demonstration_capability_mapping_uses_semantics_not_application_names() -> None:
    export_event = InteractionEvent(
        kind=InteractionKind.CONTROL_INVOKED,
        target=SemanticTarget(
            application="unfamiliar-reporting-tool",
            action_type="Export report",
        ),
    )
    draft_event = InteractionEvent(
        kind=InteractionKind.CONTROL_INVOKED,
        target=SemanticTarget(
            application="unfamiliar-reporting-tool",
            action_type="Create draft",
        ),
    )

    assert DemonstrationService._capability_for_event(export_event) == "document.export"
    assert DemonstrationService._capability_for_event(draft_event) == "draft.create"
    assert (
        DemonstrationService._capability_for_event(
            InteractionEvent(
                kind=InteractionKind.FILE_OPERATION,
                target=SemanticTarget(application="unfamiliar-reporting-tool"),
            ),
            normalized_file_operation="move",
        )
        == "file.move"
    )
