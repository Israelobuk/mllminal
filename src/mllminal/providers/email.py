"""Draft-only email providers and safe browser/system handoffs."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

from mllminal.apps.adapters import EmailDraftAdapter
from mllminal.apps.contracts import CapabilityRequest
from mllminal.providers.contracts import (
    AbstractCapability,
    ProviderAvailability,
    ProviderKind,
    ProviderRequest,
    ProviderResult,
    ProviderStatus,
)


class ClassicOutlookProvider:
    name = "outlook-classic"
    display_name = "Classic Outlook desktop (optional)"
    kind = ProviderKind.NATIVE
    priority = 10

    def __init__(self, workspace_root: Path, data_dir: Path) -> None:
        self.adapter = EmailDraftAdapter(workspace_root, data_dir)

    async def discover(self) -> ProviderAvailability:
        detected = await self.adapter.detect()
        return ProviderAvailability(
            provider=self.name,
            display_name=self.display_name,
            kind=self.kind,
            status=ProviderStatus.AVAILABLE if detected.available else ProviderStatus.UNAVAILABLE,
            detected=detected.detected,
            capabilities=[
                AbstractCapability.EMAIL_CREATE_DRAFT,
                AbstractCapability.EMAIL_SET_RECIPIENTS,
                AbstractCapability.EMAIL_SET_SUBJECT,
                AbstractCapability.EMAIL_SET_BODY,
                AbstractCapability.EMAIL_ATTACH_FILE,
                AbstractCapability.EMAIL_VERIFY_DRAFT,
            ],
            permission_scopes=["email.draft"],
            verification_strength="native-application",
            install_state="installed" if detected.detected else "not_installed",
            explanation=(
                "Classic Outlook draft automation is available."
                if detected.available
                else "Classic Outlook COM automation is unavailable; this provider is optional."
            ),
            metadata={**detected.metadata, "send_supported": False},
        )

    async def execute(self, request: ProviderRequest) -> ProviderResult:
        legacy = CapabilityRequest(
            capability=request.capability.value,
            arguments=request.arguments,
            preview=request.preview,
            workflow_authorized=request.workflow_authorized,
            action_approved=request.action_approved,
        )
        result = await self.adapter.execute(legacy)
        return ProviderResult(
            capability=request.capability,
            provider=self.name,
            succeeded=result.succeeded,
            preview=result.preview,
            draft_only=True,
            output=result.output,
            error=result.error,
        )


class ModernOutlookProvider:
    name = "outlook-modern-uia"
    display_name = "Modern Outlook UI Automation surface"
    kind = ProviderKind.NATIVE
    priority = 15

    async def discover(self) -> ProviderAvailability:
        binary = _find_any("olk.exe", "Outlook.exe")
        return ProviderAvailability(
            provider=self.name,
            display_name=self.display_name,
            kind=self.kind,
            status=ProviderStatus.MANUAL_REQUIRED if binary else ProviderStatus.UNAVAILABLE,
            detected=binary is not None,
            capabilities=[AbstractCapability.EMAIL_CREATE_DRAFT],
            permission_scopes=["email.draft", "windows.ui_automation"],
            verification_strength="semantic-ui-automation" if binary else "none",
            install_state="installed" if binary else "not_installed",
            explanation=(
                "Modern Outlook is detected, but this adapter requires an active UI Automation "
                "use the browser bridge or manual handoff when UIA is unavailable."
                if binary
                else "Modern Outlook is not detected."
            ),
            metadata={"binary": str(binary) if binary else None, "send_supported": False},
        )

    async def execute(self, request: ProviderRequest) -> ProviderResult:
        return ProviderResult(
            capability=request.capability,
            provider=self.name,
            succeeded=True,
            preview=True,
            draft_only=True,
            output={
                "operation": "manual_handoff",
                "reason": "modern_outlook_ui_automation_requires_active_surface",
                "steps": [
                    "Open modern Outlook",
                    "Review the prepared draft fields",
                    "Save as draft; do not send",
                ],
            },
        )


class BrowserEmailProvider:
    name = "browser-email"
    display_name = "Signed-in browser email surface"
    kind = ProviderKind.BROWSER
    priority = 20

    def __init__(self, browser_bridge: Any) -> None:
        self.browser_bridge = browser_bridge

    async def discover(self) -> ProviderAvailability:
        connected = bool(getattr(self.browser_bridge, "connected", False))
        return ProviderAvailability(
            provider=self.name,
            display_name=self.display_name,
            kind=self.kind,
            status=ProviderStatus.AVAILABLE if connected else ProviderStatus.MANUAL_REQUIRED,
            detected=connected,
            capabilities=[
                AbstractCapability.EMAIL_CREATE_DRAFT,
                AbstractCapability.EMAIL_SET_RECIPIENTS,
                AbstractCapability.EMAIL_SET_SUBJECT,
                AbstractCapability.EMAIL_SET_BODY,
                AbstractCapability.EMAIL_ATTACH_FILE,
                AbstractCapability.EMAIL_VERIFY_DRAFT,
            ],
            permission_scopes=["browser.email"],
            verification_strength="semantic-dom" if connected else "none",
            install_state="connected" if connected else "extension_not_connected",
            explanation=(
                "A signed-in browser email surface is connected through the local bridge."
                if connected
                else (
                    "Connect the MLLminal browser extension to prepare a draft in Gmail "
                    "or Outlook Web."
                )
            ),
            metadata={"credentials_read": False, "send_supported": False},
        )

    async def execute(self, request: ProviderRequest) -> ProviderResult:
        if not getattr(self.browser_bridge, "connected", False):
            return _failure(request, self.name, "browser_bridge_not_connected")
        output = self.browser_bridge.prepare(
            domain=str(request.arguments.get("domain", "email")),
            fields=request.arguments,
            capability=request.capability.value,
        )
        return ProviderResult(
            capability=request.capability,
            provider=self.name,
            succeeded=True,
            preview=True,
            draft_only=True,
            output=output,
        )


class SystemMailComposeProvider:
    name = "system-mail-compose"
    display_name = "System mail-compose handoff"
    kind = ProviderKind.MANUAL
    priority = 50

    async def discover(self) -> ProviderAvailability:
        return ProviderAvailability(
            provider=self.name,
            display_name=self.display_name,
            kind=self.kind,
            status=ProviderStatus.MANUAL_REQUIRED,
            capabilities=[AbstractCapability.EMAIL_CREATE_DRAFT],
            permission_scopes=["email.manual_handoff"],
            verification_strength="user-confirmed",
            explanation="Prepare an unsent mailto handoff for the user's configured mail client.",
            metadata={
                "send_supported": False,
                "manual_steps": [
                    "Review the mailto draft in your mail client.",
                    "Save it as a draft.",
                ],
            },
        )

    async def execute(self, request: ProviderRequest) -> ProviderResult:
        recipients = str(request.arguments.get("to", ""))
        subject = quote(str(request.arguments.get("subject", "")))
        body = quote(str(request.arguments.get("body", "")))
        uri = f"mailto:{quote(recipients)}?subject={subject}&body={body}"
        return ProviderResult(
            capability=request.capability,
            provider=self.name,
            succeeded=True,
            preview=True,
            draft_only=True,
            output={"operation": "system_mail_compose_handoff", "mailto": uri, "sent": False},
        )


def _find_any(*names: str) -> Path | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return Path(found)
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        candidates = list(local.glob("Microsoft/WindowsApps/olk.exe")) if local else []
        if candidates:
            return candidates[0]
    return None


def _failure(request: ProviderRequest, provider: str, error: str) -> ProviderResult:
    return ProviderResult(
        capability=request.capability,
        provider=provider,
        succeeded=False,
        preview=request.preview,
        draft_only=True,
        error=error,
    )
