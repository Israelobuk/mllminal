"""Resolve bounded capability requests through the registered adapter."""

from mllminal.apps.contracts import ApplicationAdapter
from mllminal.apps.registry import ApplicationRegistry


class CapabilityResolver:
    def __init__(self, registry: ApplicationRegistry) -> None:
        self.registry = registry

    def resolve(self, application: str) -> ApplicationAdapter:
        return self.registry.get(application)
