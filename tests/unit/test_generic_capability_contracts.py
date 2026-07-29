from mllminal.apps.contracts import (
    CapabilityConsequence,
    CapabilityDefinition,
    CapabilityMode,
)
from mllminal.providers.contracts import AbstractCapability


def test_generic_capability_vocabulary_covers_reusable_device_actions() -> None:
    expected = {
        "application.launch",
        "application.focus",
        "application.close",
        "application.inspect_state",
        "window.find",
        "window.focus",
        "control.find",
        "control.invoke",
        "field.set",
        "field.clear",
        "field.select",
        "field.verify",
        "keyboard.shortcut",
        "keyboard.text_intent",
        "pointer.click",
        "pointer.double_click",
        "menu.open",
        "menu.select",
        "dialog.detect",
        "dialog.confirm",
        "dialog.cancel",
        "browser.navigate",
        "browser.inspect_dom",
        "browser.extract_structured",
        "browser.download",
        "file.locate",
        "file.copy",
        "file.move",
        "file.rename",
        "file.transform",
        "file.verify",
        "document.open",
        "document.edit",
        "document.save",
        "document.export",
        "table.read",
        "table.write",
        "table.append",
        "table.verify",
        "draft.create",
        "draft.attach",
        "draft.verify_unsent",
        "state.wait",
        "state.verify",
        "result.capture",
    }

    assert expected <= {capability.value for capability in AbstractCapability}


def test_capability_definition_declares_consequence_and_verification_boundary() -> None:
    definition = CapabilityDefinition(
        name="field.set",
        display_name="Set a semantic field",
        mode=CapabilityMode.PREVIEW,
        permission_scope="application.write",
        consequential=True,
        consequence=CapabilityConsequence.REVERSIBLE,
        requires_independent_verification=True,
    )

    assert definition.consequence is CapabilityConsequence.REVERSIBLE
    assert definition.requires_independent_verification is True
