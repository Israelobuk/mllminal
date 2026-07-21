"""Permissioned browser bridge seam that retains authentication in the browser."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class BrowserBridgeGrant:
    domain: str
    capabilities: set[str] = field(default_factory=set)
    granted_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class BrowserBridge:
    """Bounded browser-surface seam; cookies and tokens are intentionally opaque.

    The native bridge receives semantic field operations from the extension. It
    never accepts cookies, tokens, passwords, or arbitrary script text.
    """

    blocked_path_fragments = (
        "/login",
        "/signin",
        "/signup",
        "/checkout",
        "/payment",
        "/security",
        "/account/recovery",
    )

    def __init__(self) -> None:
        self.connected = False
        self._grants: dict[str, BrowserBridgeGrant] = {}

    def connect(self, *, extension_id: str, browser_name: str) -> None:
        if not extension_id or not browser_name:
            raise ValueError("browser_bridge_identity_required")
        self.connected = True

    def grant_domain(self, *, domain: str, capabilities: set[str]) -> BrowserBridgeGrant:
        if not domain or not capabilities:
            raise ValueError("browser_domain_grant_required")
        grant = BrowserBridgeGrant(domain=domain.casefold(), capabilities=set(capabilities))
        self._grants[grant.domain] = grant
        return grant

    def prepare(self, *, domain: str, fields: dict[str, Any], capability: str) -> dict[str, Any]:
        if not self.connected:
            raise RuntimeError("browser_bridge_not_connected")
        normalized_domain = domain.casefold()
        grant = self._grants.get(normalized_domain)
        if grant is None or capability not in grant.capabilities:
            raise PermissionError("browser_domain_capability_not_granted")
        path = str(fields.get("path", "")).casefold()
        if any(fragment in path for fragment in self.blocked_path_fragments):
            raise PermissionError("browser_security_or_payment_surface_blocked")
        if any(key.casefold() in {"cookie", "token", "password", "secret"} for key in fields):
            raise PermissionError("browser_credential_field_blocked")
        return {
            "domain": normalized_domain,
            "capability": capability,
            "draft_fields": dict(fields),
            "sent": False,
            "credentials_read": False,
            "visible_indicator": "mllminal-active",
        }

    def create_draft(self, *, domain: str, fields: dict[str, Any]) -> dict[str, Any]:
        self.connected = True
        self.grant_domain(domain=domain, capabilities={"email.create_draft"})
        return self.prepare(domain=domain, fields=fields, capability="email.create_draft")
