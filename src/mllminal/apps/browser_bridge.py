"""Browser bridge seam that retains authentication in the browser."""

from typing import Any


class BrowserBridge:
    """Bounded browser-surface seam; cookies and tokens are intentionally opaque."""

    def create_draft(self, *, domain: str, fields: dict[str, Any]) -> dict[str, Any]:
        return {
            "domain": domain,
            "draft_fields": fields,
            "sent": False,
            "credentials_read": False,
        }
