"""Windows UI Automation seam; it never reads credentials or browser secrets."""

from typing import Any


class WindowsUIAutomation:
    """Provider-neutral placeholder for bounded accessibility resolution."""

    def resolve_control(self, *, application: str, control_name: str) -> dict[str, Any]:
        return {
            "application": application,
            "control_name": control_name,
            "resolved": False,
            "reason": "windows_ui_provider_not_configured",
        }
