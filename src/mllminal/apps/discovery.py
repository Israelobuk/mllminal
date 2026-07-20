"""Provider-neutral application discovery facade."""

from mllminal.apps.contracts import (
    ApplicationAdapter,
    ApplicationAvailability,
    CapabilityDefinition,
)
from mllminal.apps.registry import ApplicationRegistry


class ApplicationDiscovery:
    def __init__(self, registry: ApplicationRegistry) -> None:
        self.registry = registry

    async def discover(self) -> list[ApplicationAvailability]:
        return [await adapter.detect() for adapter in self.registry.all()]

    async def capabilities(self, application: str) -> list[CapabilityDefinition]:
        adapter: ApplicationAdapter = self.registry.get(application)
        return await adapter.capabilities()
