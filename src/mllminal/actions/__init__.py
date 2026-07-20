"""Explicitly authorized, allowlisted device action boundaries."""

from mllminal.actions.contracts import ActionRequest, ActionResult
from mllminal.actions.service import BoundedActionService

__all__ = ["ActionRequest", "ActionResult", "BoundedActionService"]
