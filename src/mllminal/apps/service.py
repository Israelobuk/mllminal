"""Permissioned application bridge service."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as DbSession

from mllminal.apps.adapters import EmailDraftAdapter, ExcelAdapter
from mllminal.apps.contracts import (
    ApplicationAvailability,
    ApplicationGrant,
    ApplicationState,
    CapabilityDefinition,
    CapabilityRequest,
    CapabilityResult,
    VerificationResult,
)
from mllminal.apps.discovery import ApplicationDiscovery
from mllminal.apps.filesystem import FilesystemAdapter
from mllminal.apps.permissions import ApplicationBridgeIdempotencyRow, ApplicationGrantRow
from mllminal.apps.registry import ApplicationRegistry
from mllminal.contracts import utc_now
from mllminal.persistence import Base
from mllminal.providers.contracts import (
    AbstractCapability,
    CapabilityResolution,
    ProviderAvailability,
    ProviderRequest,
    ProviderResult,
)
from mllminal.providers.defaults import create_default_resolver


class ApplicationBridgeService:
    def __init__(
        self,
        database_path: Path,
        workspace_root: Path | None = None,
        emergency_stop_active: Callable[[], bool] | None = None,
    ) -> None:
        self.database_path = database_path
        self._emergency_stop_active = emergency_stop_active or (lambda: False)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{database_path}")
        Base.metadata.create_all(self.engine)
        self.registry = ApplicationRegistry()
        self.registry.register(
            FilesystemAdapter(
                workspace_root,
                data_dir=self.database_path.parent / "filesystem",
            )
        )
        self.registry.register(ExcelAdapter(workspace_root, self.database_path.parent / "excel"))
        self.registry.register(
            EmailDraftAdapter(workspace_root, self.database_path.parent / "email")
        )
        self.discovery = ApplicationDiscovery(self.registry)
        self.provider_resolver = create_default_resolver(
            self.database_path,
            (workspace_root or Path.cwd()).expanduser().resolve(),
        )

    async def discover(self) -> list[ApplicationAvailability]:
        values = await self.discovery.discover()
        grants = {grant.application for grant in self.grants() if grant.granted}
        return [
            value.model_copy(
                update={
                    "state": (
                        ApplicationState.CAPABILITIES_GRANTED
                        if value.application in grants
                        else value.state
                    )
                }
            )
            for value in values
        ]

    async def capabilities(self, application: str) -> list[CapabilityDefinition]:
        return list(await self.discovery.capabilities(application))

    async def provider_discovery(self) -> list[ProviderAvailability]:
        """Discover providers without requiring any desktop application."""

        return await self.provider_resolver.discover()

    async def resolve_capability(
        self, capability: AbstractCapability | str, *, preferred_provider: str | None = None
    ) -> CapabilityResolution:
        return await self.provider_resolver.resolve(
            capability, preferred_provider=preferred_provider
        )

    async def execute_capability(
        self,
        request: ProviderRequest,
        *,
        idempotency_key: str,
    ) -> ProviderResult:
        cached = self._cached(idempotency_key, "provider.execute")
        if cached is not None:
            return ProviderResult.model_validate(cached)
        if self._emergency_stop_active():
            raise PermissionError("Emergency stop active")
        resolution = await self.resolve_capability(request.capability)
        if resolution.provider is None:
            return ProviderResult(
                capability=request.capability,
                provider="unsupported",
                succeeded=False,
                preview=request.preview,
                error=resolution.explanation,
            )
        if not request.preview and not request.workflow_authorized:
            raise PermissionError("Workflow authorization is required")
        provider = self.provider_resolver.registry.get(resolution.provider)
        try:
            result = await provider.execute(request)
        except Exception as error:
            result = ProviderResult(
                capability=request.capability,
                provider=resolution.provider,
                succeeded=False,
                preview=request.preview,
                error=str(error) or "provider_execution_failed",
            )
        self._save_idempotency(idempotency_key, "provider.execute", result)
        return result

    def grant(self, application: str, scope: str, *, idempotency_key: str) -> ApplicationGrant:
        cached = self._cached(idempotency_key, "app.grant")
        if cached is not None:
            return ApplicationGrant.model_validate(cached)
        self.registry.get(application)
        grant = ApplicationGrant(application=application, scope=scope)
        with DbSession(self.engine) as database, database.begin():
            database.add(
                ApplicationGrantRow(
                    id=grant.id,
                    application=grant.application,
                    scope=grant.scope,
                    granted=grant.granted,
                    updated_at=grant.updated_at,
                )
            )
        self._save_idempotency(idempotency_key, "app.grant", grant)
        return grant

    def grants(self) -> list[ApplicationGrant]:
        with DbSession(self.engine) as database:
            rows = database.scalars(
                select(ApplicationGrantRow).order_by(ApplicationGrantRow.updated_at)
            )
            return [
                ApplicationGrant(
                    id=row.id,
                    application=row.application,
                    scope=row.scope,
                    granted=row.granted,
                    updated_at=row.updated_at,
                )
                for row in rows
            ]

    async def execute(
        self,
        application: str,
        request: CapabilityRequest,
        *,
        idempotency_key: str,
    ) -> CapabilityResult:
        cached = self._cached(idempotency_key, "app.execute")
        if cached is not None:
            return CapabilityResult.model_validate(cached)
        if self._emergency_stop_active():
            raise PermissionError("Emergency stop active")
        capabilities = await self.capabilities(application)
        definition = next((item for item in capabilities if item.name == request.capability), None)
        if definition is None:
            raise KeyError(request.capability)
        if not request.preview:
            if not request.workflow_authorized or not request.action_approved:
                raise PermissionError("Workflow authorization and action approval are required")
            if not any(
                grant.granted
                and grant.application == application
                and grant.scope == definition.permission_scope
                for grant in self.grants()
            ):
                raise PermissionError("Application capability grant is required")
        result = await self.registry.get(application).execute(request)
        self._save_idempotency(idempotency_key, "app.execute", result)
        return result

    async def verify(self, application: str, result: CapabilityResult) -> VerificationResult:
        if not self._is_persisted_execution(result):
            raise PermissionError("Verification requires a persisted bridge execution result")
        return await self.registry.get(application).verify(result)

    def _is_persisted_execution(self, result: CapabilityResult) -> bool:
        with DbSession(self.engine) as database:
            rows = database.scalars(
                select(ApplicationBridgeIdempotencyRow).where(
                    ApplicationBridgeIdempotencyRow.operation == "app.execute"
                )
            )
            for row in rows:
                if json.loads(row.result_json) == result.model_dump(mode="json"):
                    return True
        return False

    def _cached(self, key: str, operation: str) -> dict[str, Any] | None:
        with DbSession(self.engine) as database:
            row = database.execute(
                select(ApplicationBridgeIdempotencyRow).where(
                    ApplicationBridgeIdempotencyRow.key == key
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            if row.operation != operation:
                raise ValueError("Idempotency key was already used for a different operation")
            return cast(dict[str, Any], json.loads(row.result_json))

    def _save_idempotency(self, key: str, operation: str, result: Any) -> None:
        with DbSession(self.engine) as database, database.begin():
            database.add(
                ApplicationBridgeIdempotencyRow(
                    key=key,
                    operation=operation,
                    result_json=result.model_dump_json(),
                    created_at=utc_now(),
                )
            )
