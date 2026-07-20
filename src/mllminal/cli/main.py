"""Typer command-line interface for local model selection."""

import asyncio
import json
from collections.abc import Awaitable, Callable

import typer

from mllminal.actions.contracts import ActionRequest
from mllminal.actions.service import BoundedActionService
from mllminal.activity.service import ActivityService
from mllminal.agent.ollama import OllamaClient, OllamaProviderError
from mllminal.apps.contracts import CapabilityRequest
from mllminal.apps.service import ApplicationBridgeService
from mllminal.assistance.contracts import AssistanceRequest
from mllminal.assistance.service import ProactiveAssistanceService
from mllminal.config import ProviderConfig, ProviderConfigStore, Settings
from mllminal.demonstration.contracts import (
    DemonstrationCaptureRequest,
    VariableLabel,
)
from mllminal.demonstration.service import DemonstrationService
from mllminal.device.observer import DeviceObserver
from mllminal.interaction.contracts import InteractionEvent
from mllminal.interaction.service import InteractionService
from mllminal.langgraph.adapter import LangGraphWorkflowAdapter
from mllminal.learning.contracts import PolicyVersion
from mllminal.learning.evaluation import EvaluationCase
from mllminal.learning.governance import CandidateGovernanceService, PromotionApprovalError
from mllminal.learning.registry import PolicyRegistry
from mllminal.learning.replay import LearningRepository
from mllminal.learning.service import CandidateTrainingService, MinimumExperienceError
from mllminal.mining.contracts import MiningRequest
from mllminal.mining.service import WorkflowMiningService
from mllminal.privacy.contracts import (
    CaptureCategory,
    CaptureContext,
    CaptureRequest,
    PrivacyRule,
    PrivacyRuleType,
)
from mllminal.privacy.service import PrivacyService
from mllminal.verification.contracts import LocalVisualObservation, VisualVerificationRequest
from mllminal.verification.service import LocalVisualVerificationService
from mllminal.workflow.contracts import WorkflowDefinition, WorkflowRunRequest
from mllminal.workflow.service import WorkflowService

ModelProbe = Callable[[ProviderConfig], Awaitable[bool]]


async def _await_probe(probe: ModelProbe, config: ProviderConfig) -> bool:
    return await probe(config)


async def _probe_model(config: ProviderConfig) -> bool:
    async with OllamaClient(
        config.base_url,
        config.model,
        timeout_seconds=config.request_timeout_seconds,
    ) as client:
        return await client.model_available()


def create_app(
    settings: Settings | None = None,
    *,
    model_probe: ModelProbe | None = None,
) -> typer.Typer:
    """Create the CLI with injectable settings and model probe for local tests."""
    resolved_settings = settings or Settings()
    store = ProviderConfigStore(resolved_settings)
    probe = model_probe or _probe_model
    app = typer.Typer(help="MLLminal local-first AI execution environment.")
    models = typer.Typer(
        help="Inspect and select Mil model providers.", invoke_without_command=True
    )
    learning = typer.Typer(help="Inspect and train local candidate policies.")
    device = typer.Typer(help="Control metadata-only local device observation.")
    privacy = typer.Typer(help="Control consent, capture, exclusions, and privacy history.")
    interaction = typer.Typer(help="Capture semantic interactions and manage replay permission.")
    demonstrate = typer.Typer(help="Teach MLLminal an explicit workflow.")
    activity = typer.Typer(help="Model activity, application sessions, and task sessions.")
    workflow = typer.Typer(help="Define, preview, approve, and verify typed workflows.")
    apps = typer.Typer(help="Discover and grant bounded on-device application capabilities.")
    visual = typer.Typer(help="Record and verify local semantic visual observations.")
    mining = typer.Typer(help="Mine repeated semantic interactions into workflow candidates.")
    actions = typer.Typer(help="Preview and explicitly approve bounded device actions.")
    assist = typer.Typer(help="Surface reviewable workflow suggestions without executing them.")
    adapters = typer.Typer(help="Export typed workflows to optional local adapters.")
    incognito = typer.Typer(help="Control private observation sessions.")
    exclude = typer.Typer(help="Add privacy exclusions.")

    def observer() -> DeviceObserver:
        return DeviceObserver(resolved_settings.data_dir / "device", [])

    def current() -> ProviderConfig:
        return store.load()

    def display(config: ProviderConfig, connection: str | None = None) -> None:
        label = "Qwen" if config.provider == "qwen" else "Deterministic fixture"
        typer.echo(f"Mil provider: {label}")
        typer.echo(f"Model: {config.model}")
        typer.echo(f"Endpoint: {config.base_url}")
        if connection is not None:
            typer.echo(f"Connection: {connection}")
        typer.echo("Streaming: Enabled")
        typer.echo(f"Context limit: {config.max_context_tokens}")

    def check(config: ProviderConfig) -> tuple[bool, str]:
        if config.provider == "deterministic":
            return True, "Available"
        try:
            return asyncio.run(_await_probe(probe, config)), "Available"
        except OllamaProviderError as error:
            return False, f"Unavailable ({error.category})"

    @models.callback()
    def models_root(context: typer.Context) -> None:
        if context.invoked_subcommand is None:
            display(current())

    @models.command("status")
    def status() -> None:
        config = current()
        available, connection = check(config)
        display(config, connection)
        if not available:
            raise typer.Exit(code=1)

    @models.command("provider")
    def provider() -> None:
        typer.echo(current().provider)

    @models.command("use")
    def use(provider_name: str) -> None:
        if provider_name not in {"qwen", "deterministic"}:
            raise typer.BadParameter("Provider must be qwen or deterministic")
        config = current()
        updated = config.model_copy(update={"provider": provider_name})
        store.save(updated)
        label = "Qwen" if updated.provider == "qwen" else "Deterministic fixture"
        typer.echo(f"Mil provider switched to: {label}")

    @models.command("test")
    def test() -> None:
        config = current()
        if config.provider == "deterministic":
            typer.echo("Deterministic fixture mode does not contact a model server.")
            return
        available, connection = check(config)
        if available:
            typer.echo(f"Qwen model is available at {config.base_url}.")
            return
        typer.echo("Mil provider unavailable")
        typer.echo(
            f"MLLminal could not connect to the configured local model server at {config.base_url}."
        )
        typer.echo("Start the local model service or run: mllminal models use deterministic")
        typer.echo(f"Connection: {connection}")
        raise typer.Exit(code=1)

    def privacy_service() -> PrivacyService:
        return PrivacyService(resolved_settings.database_path)

    def interaction_service() -> InteractionService:
        return InteractionService(resolved_settings.database_path, privacy_service())

    def demonstration_service() -> DemonstrationService:
        return DemonstrationService(resolved_settings.database_path, interaction_service())

    def activity_service() -> ActivityService:
        return ActivityService(
            resolved_settings.database_path,
            interaction_service(),
            observer(),
        )

    def workflow_service() -> WorkflowService:
        return WorkflowService(resolved_settings.database_path)

    def application_service() -> ApplicationBridgeService:
        return ApplicationBridgeService(resolved_settings.database_path)

    def visual_service() -> LocalVisualVerificationService:
        return LocalVisualVerificationService(resolved_settings.data_dir / "visual")

    def mining_service() -> WorkflowMiningService:
        return WorkflowMiningService()

    def action_service() -> BoundedActionService:
        return BoundedActionService()

    def assistance_service() -> ProactiveAssistanceService:
        return ProactiveAssistanceService()

    def langgraph_adapter() -> LangGraphWorkflowAdapter:
        return LangGraphWorkflowAdapter()

    def demonstration_session_id(session_id: str | None) -> str:
        current = demonstration_service().status().session
        value = session_id or (current.id if current else None)
        if value is None:
            typer.echo("No demonstration session is available.")
            raise typer.Exit(code=1)
        return value

    @learning.command("status")
    def learning_status() -> None:
        repository = LearningRepository(resolved_settings.database_path)
        repository.initialize()
        status = repository.get_settings()
        typer.echo(f"Learning: {'Enabled' if status.enabled else 'Disabled'}")
        typer.echo(
            "Automatic promotion: "
            f"{'Enabled' if status.automatic_promotion_enabled else 'Disabled'}"
        )
        typer.echo(f"Eligible experiences: {status.eligible_experience_count}")
        typer.echo(f"Minimum experiences: {status.minimum_experience_count}")
        typer.echo(f"Active policy: {status.active_policy_version_id or 'policy_v0'}")

    def governance() -> CandidateGovernanceService:
        repository = LearningRepository(resolved_settings.database_path)
        repository.initialize()
        return CandidateGovernanceService(
            repository,
            PolicyRegistry(repository, resolved_settings.data_dir / "learning" / "checkpoints"),
        )

    def named_policy(name: str) -> PolicyVersion:
        matches = [
            policy
            for policy in governance().repository.list_policy_versions()
            if policy.name == name
        ]
        if len(matches) != 1:
            typer.echo(f"Unknown policy: {name}")
            raise typer.Exit(code=1)
        return matches[0]

    @learning.command("evaluate")
    def evaluate_learning(policy_name: str) -> None:
        policy = named_policy(policy_name)
        if policy.training_run_id is None:
            typer.echo("Policy has no training run to evaluate.")
            raise typer.Exit(code=1)
        service = governance()
        samples = service.repository.sample_replay(
            service.repository.count_replay_entries(), seed=service.repository.get_settings().seed
        )
        if not samples:
            typer.echo("No held-out replay samples are available.")
            raise typer.Exit(code=1)
        result = service.evaluate(
            policy.id,
            policy.training_run_id,
            [EvaluationCase(sample=sample, action_mask=(True,) * 9) for sample in samples],
        )
        typer.echo(f"Evaluation: {'passed' if result.report.passed else 'rejected'}")
        typer.echo(f"Report: {result.report.id}")

    @learning.command("compare")
    def compare_learning(candidate_name: str, current_name: str) -> None:
        candidate = named_policy(candidate_name)
        current = named_policy(current_name)
        typer.echo(f"Candidate: {candidate.name}")
        typer.echo(f"Current: {current.name}")
        typer.echo("Use 'learning evaluate' to produce the durable comparison metrics.")

    @learning.command("promote")
    def promote_learning(candidate_name: str) -> None:
        candidate = named_policy(candidate_name)
        reports = [
            report
            for report in governance().repository.list_evaluation_reports()
            if report.candidate_policy_id == candidate.id
        ]
        if not reports:
            typer.echo("Candidate has no evaluation report.")
            raise typer.Exit(code=1)
        try:
            promoted = governance().promote(
                candidate.id,
                reports[-1].id,
                explicitly_approved=True,
                idempotency_key=f"cli-promote-{candidate.id}",
            )
        except PromotionApprovalError as error:
            typer.echo(str(error))
            raise typer.Exit(code=1) from None
        typer.echo(f"Promoted: {promoted.name}")

    @learning.command("rollback")
    def rollback_learning() -> None:
        try:
            record = governance().rollback(
                reason="CLI operator rollback", idempotency_key="cli-rollback"
            )
        except KeyError:
            typer.echo("No previous promoted policy is available for rollback.")
            raise typer.Exit(code=1) from None
        typer.echo(f"Rolled back to: {record.to_policy_version_id}")

    @learning.command("train")
    def train_learning() -> None:
        repository = LearningRepository(resolved_settings.database_path)
        repository.initialize()
        try:
            result = CandidateTrainingService(
                repository, resolved_settings.data_dir / "learning"
            ).train()
        except MinimumExperienceError:
            typer.echo("Cannot train: minimum eligible experience threshold is not met.")
            raise typer.Exit(code=1) from None
        typer.echo(f"Candidate policy: {result.candidate.name}")
        typer.echo(f"Training run: {result.training_run.id}")
        typer.echo(f"Checkpoint: {result.checkpoint}")

    @device.command("status")
    def device_status() -> None:
        typer.echo(observer().status.state)

    @device.command("start")
    def device_start() -> None:
        value = observer()
        value.start()
        typer.echo(value.status.state)

    @device.command("stop")
    def device_stop() -> None:
        value = observer()
        value.stop()
        typer.echo(value.status.state)

    @device.command("pause")
    def device_pause() -> None:
        value = observer()
        value.pause()
        typer.echo(value.status.state)

    @device.command("resume")
    def device_resume() -> None:
        value = observer()
        value.resume()
        typer.echo(value.status.state)

    @device.command("capabilities")
    def device_capabilities() -> None:
        for capability in observer().capabilities():
            typer.echo(capability.name)

    @device.command("events")
    def device_events() -> None:
        for event in observer().events():
            typer.echo(event.model_dump_json())

    @interaction.command("status")
    def interaction_status() -> None:
        typer.echo(interaction_service().status().model_dump_json())

    @interaction.command("replay-authorize")
    def interaction_replay_authorize() -> None:
        typer.echo(
            interaction_service()
            .authorize_replay(idempotency_key="cli-interaction-replay-authorize")
            .model_dump_json()
        )

    @interaction.command("replay-revoke")
    def interaction_replay_revoke() -> None:
        typer.echo(
            interaction_service()
            .revoke_replay(idempotency_key="cli-interaction-replay-revoke")
            .model_dump_json()
        )

    @interaction.command("capture")
    def interaction_capture(
        payload: str,
        idempotency_key: str | None = typer.Option(None, "--idempotency-key"),
    ) -> None:
        event = InteractionEvent.model_validate_json(payload)
        key = idempotency_key or f"cli-interaction-{event.id}"
        typer.echo(interaction_service().capture(event, idempotency_key=key).model_dump_json())

    @interaction.command("events")
    def interaction_events() -> None:
        for event in interaction_service().events():
            typer.echo(event.model_dump_json())

    @demonstrate.command("status")
    def demonstrate_status(session_id: str | None = typer.Argument(default=None)) -> None:
        typer.echo(demonstration_service().status(session_id).model_dump_json())

    @demonstrate.command("start")
    def demonstrate_start(
        label: str,
        timeout_seconds: int = typer.Option(900, "--timeout-seconds", min=1, max=3600),
        emergency_stop_shortcut: str = typer.Option("CTRL+ALT+ESC", "--emergency-stop-shortcut"),
    ) -> None:
        typer.echo(
            demonstration_service()
            .start(
                label,
                timeout_seconds=timeout_seconds,
                emergency_stop_shortcut=emergency_stop_shortcut,
                idempotency_key=f"cli-demonstrate-start-{label}",
            )
            .model_dump_json()
        )

    @demonstrate.command("stop")
    def demonstrate_stop(session_id: str | None = typer.Argument(default=None)) -> None:
        value = demonstration_session_id(session_id)
        typer.echo(
            demonstration_service()
            .stop(value, idempotency_key=f"cli-demonstrate-stop-{value}")
            .model_dump_json()
        )

    @demonstrate.command("cancel")
    def demonstrate_cancel(session_id: str | None = typer.Argument(default=None)) -> None:
        value = demonstration_session_id(session_id)
        typer.echo(
            demonstration_service()
            .cancel(value, idempotency_key=f"cli-demonstrate-cancel-{value}")
            .model_dump_json()
        )

    @demonstrate.command("emergency-stop")
    def demonstrate_emergency_stop(session_id: str | None = typer.Argument(default=None)) -> None:
        value = demonstration_session_id(session_id)
        typer.echo(
            demonstration_service()
            .emergency_stop(value, idempotency_key=f"cli-demonstrate-emergency-{value}")
            .model_dump_json()
        )

    @demonstrate.command("record")
    def demonstrate_record(
        session_id: str,
        payload: str,
        normalized_file_operation: str | None = typer.Option(default=None),
        application_transition: str | None = typer.Option(default=None),
        text_entry_occurred: bool = typer.Option(default=False),
    ) -> None:
        event = InteractionEvent.model_validate_json(payload)
        request = DemonstrationCaptureRequest(
            event=event,
            normalized_file_operation=normalized_file_operation,
            application_transition=application_transition,
            text_entry_occurred=text_entry_occurred,
        )
        typer.echo(
            demonstration_service()
            .record(session_id, request, idempotency_key=f"cli-demonstrate-record-{event.id}")
            .model_dump_json()
        )

    @demonstrate.command("steps")
    def demonstrate_steps(session_id: str | None = typer.Argument(default=None)) -> None:
        value = demonstration_session_id(session_id)
        for step in demonstration_service().steps(value):
            typer.echo(step.model_dump_json())

    @demonstrate.command("label")
    def demonstrate_label(
        session_id: str,
        event_id: str,
        label: VariableLabel,
        field_name: str | None = typer.Option(default=None),
    ) -> None:
        typer.echo(
            demonstration_service()
            .assign_variable(
                session_id,
                event_id,
                label,
                field_name=field_name,
                idempotency_key=f"cli-demonstrate-label-{session_id}-{event_id}",
            )
            .model_dump_json()
        )

    @demonstrate.command("candidate")
    def demonstrate_candidate(candidate_id: str) -> None:
        typer.echo(demonstration_service().candidate(candidate_id).model_dump_json())

    @activity.command("refresh")
    def activity_refresh(
        lookback_minutes: int = typer.Option(1440, "--lookback-minutes", min=1, max=10080),
    ) -> None:
        typer.echo(
            activity_service()
            .refresh(
                lookback_minutes=lookback_minutes,
                idempotency_key=f"cli-activity-refresh-{lookback_minutes}",
            )
            .model_dump_json()
        )

    @activity.command("status")
    def activity_status() -> None:
        summary = activity_service().summary()
        typer.echo(summary.model_dump_json() if summary else "{}")

    @activity.command("segments")
    def activity_segments() -> None:
        for item in activity_service().segments():
            typer.echo(item.model_dump_json())

    @activity.command("applications")
    def activity_applications() -> None:
        for item in activity_service().application_sessions():
            typer.echo(item.model_dump_json())

    @activity.command("tasks")
    def activity_tasks() -> None:
        for item in activity_service().task_sessions():
            typer.echo(item.model_dump_json())

    @activity.command("context-switches")
    def activity_context_switches() -> None:
        for item in activity_service().context_switches():
            typer.echo(item.model_dump_json())

    @activity.command("boundaries")
    def activity_boundaries() -> None:
        for item in activity_service().task_boundaries():
            typer.echo(item.model_dump_json())

    @workflow.command("create")
    def workflow_create(payload: str) -> None:
        definition = WorkflowDefinition.model_validate_json(payload)
        typer.echo(
            workflow_service()
            .create(definition, idempotency_key=f"cli-workflow-create-{definition.id}")
            .model_dump_json()
        )

    @workflow.command("list")
    def workflow_list() -> None:
        for item in workflow_service().definitions():
            typer.echo(item.model_dump_json())

    @workflow.command("activate")
    def workflow_activate(workflow_id: str) -> None:
        typer.echo(
            workflow_service()
            .activate(workflow_id, idempotency_key=f"cli-workflow-activate-{workflow_id}")
            .model_dump_json()
        )

    @workflow.command("archive")
    def workflow_archive(workflow_id: str) -> None:
        typer.echo(
            workflow_service()
            .archive(workflow_id, idempotency_key=f"cli-workflow-archive-{workflow_id}")
            .model_dump_json()
        )

    @workflow.command("preview")
    def workflow_preview(workflow_id: str, inputs: str = "{}") -> None:
        request = WorkflowRunRequest(
            inputs=json.loads(inputs),
            preview=True,
        )
        typer.echo(
            workflow_service()
            .run(workflow_id, request, idempotency_key=f"cli-workflow-preview-{workflow_id}")
            .model_dump_json()
        )

    @workflow.command("run")
    def workflow_run(
        workflow_id: str,
        inputs: str = "{}",
        live: bool = typer.Option(False, "--live"),
    ) -> None:
        request = WorkflowRunRequest(inputs=json.loads(inputs), preview=not live)
        typer.echo(
            workflow_service()
            .run(workflow_id, request, idempotency_key=f"cli-workflow-run-{workflow_id}")
            .model_dump_json()
        )

    @workflow.command("approve")
    def workflow_approve(run_id: str, approved: bool = typer.Option(..., "--approved")) -> None:
        typer.echo(
            workflow_service()
            .approve(run_id, approved, idempotency_key=f"cli-workflow-approve-{run_id}")
            .model_dump_json()
        )

    @workflow.command("rollback")
    def workflow_rollback(run_id: str) -> None:
        typer.echo(
            workflow_service()
            .rollback(run_id, idempotency_key=f"cli-workflow-rollback-{run_id}")
            .model_dump_json()
        )

    @workflow.command("runs")
    def workflow_runs() -> None:
        for item in workflow_service().runs():
            typer.echo(item.model_dump_json())

    @workflow.command("events")
    def workflow_events(run_id: str) -> None:
        for item in workflow_service().events(run_id):
            typer.echo(item.model_dump_json())

    @apps.command("discover")
    def apps_discover() -> None:
        for item in asyncio.run(application_service().discover()):
            typer.echo(item.model_dump_json())

    @apps.command("grants")
    def apps_grants() -> None:
        for item in application_service().grants():
            typer.echo(item.model_dump_json())

    @apps.command("capabilities")
    def apps_capabilities(application: str) -> None:
        for item in asyncio.run(application_service().capabilities(application)):
            typer.echo(item.model_dump_json())

    @apps.command("grant")
    def apps_grant(application: str, scope: str) -> None:
        typer.echo(
            application_service()
            .grant(application, scope, idempotency_key=f"cli-app-grant-{application}-{scope}")
            .model_dump_json()
        )

    @apps.command("execute")
    def apps_execute(application: str, payload: str) -> None:
        request = CapabilityRequest.model_validate_json(payload)
        typer.echo(
            asyncio.run(
                application_service().execute(
                    application,
                    request,
                    idempotency_key=f"cli-app-execute-{application}-{request.capability}",
                )
            ).model_dump_json()
        )

    @visual.command("observe")
    def visual_observe(payload: str) -> None:
        typer.echo(
            visual_service()
            .observe(LocalVisualObservation.model_validate_json(payload))
            .model_dump_json()
        )

    @visual.command("latest")
    def visual_latest() -> None:
        latest = visual_service().latest()
        if latest is not None:
            typer.echo(latest.model_dump_json())

    @visual.command("verify")
    def visual_verify(payload: str) -> None:
        typer.echo(
            visual_service()
            .verify(VisualVerificationRequest.model_validate_json(payload))
            .model_dump_json()
        )

    @mining.command("run")
    def mining_run(payload: str = "{}") -> None:
        request = MiningRequest.model_validate_json(payload)
        typer.echo(mining_service().mine(interaction_service().events(), request).model_dump_json())

    @actions.command("list")
    def actions_list() -> None:
        for action in action_service().actions():
            typer.echo(action)

    @actions.command("execute")
    def actions_execute(payload: str) -> None:
        request = ActionRequest.model_validate_json(payload)
        typer.echo(
            action_service()
            .execute(request, idempotency_key=f"cli-action-{request.action}")
            .model_dump_json()
        )

    @assist.command("suggest")
    def assist_suggest(payload: str = "{}") -> None:
        request = AssistanceRequest.model_validate_json(payload)
        mined = WorkflowMiningService().mine(interaction_service().events(), request.mining)
        typer.echo(assistance_service().suggest(mined, request).model_dump_json())

    @adapters.command("langgraph")
    def adapter_langgraph(payload: str) -> None:
        definition = WorkflowDefinition.model_validate_json(payload)
        adapter = langgraph_adapter()
        typer.echo(
            json.dumps(
                {
                    "available": adapter.available(),
                    "spec": adapter.spec(definition).model_dump(mode="json"),
                }
            )
        )

    @privacy.command("status")
    def privacy_status() -> None:
        typer.echo(privacy_service().status().model_dump_json())

    @privacy.command("enable")
    def privacy_enable() -> None:
        typer.echo(privacy_service().enable(idempotency_key="cli-enable").model_dump_json())

    @privacy.command("disable")
    def privacy_disable() -> None:
        typer.echo(privacy_service().disable(idempotency_key="cli-disable").model_dump_json())

    @privacy.command("pause")
    def privacy_pause() -> None:
        typer.echo(privacy_service().pause(idempotency_key="cli-pause").model_dump_json())

    @privacy.command("resume")
    def privacy_resume() -> None:
        typer.echo(privacy_service().resume(idempotency_key="cli-resume").model_dump_json())

    @incognito.command("start")
    def privacy_incognito_start() -> None:
        typer.echo(
            privacy_service()
            .start_incognito(idempotency_key="cli-incognito-start")
            .model_dump_json()
        )

    @incognito.command("stop")
    def privacy_incognito_stop() -> None:
        typer.echo(
            privacy_service().stop_incognito(idempotency_key="cli-incognito-stop").model_dump_json()
        )

    @privacy.command("emergency-stop")
    def privacy_emergency_stop() -> None:
        typer.echo(
            privacy_service().emergency_stop(idempotency_key="cli-emergency-stop").model_dump_json()
        )

    @privacy.command("emergency-clear")
    def privacy_emergency_clear() -> None:
        typer.echo(
            privacy_service()
            .emergency_clear(idempotency_key="cli-emergency-clear")
            .model_dump_json()
        )

    @privacy.command("exclusions")
    def privacy_exclusions() -> None:
        for rule in privacy_service().exclusions():
            typer.echo(rule.model_dump_json())

    @exclude.command("app")
    def privacy_exclude_app(application: str) -> None:
        rule = PrivacyRule(rule_type=PrivacyRuleType.APPLICATION, pattern=application)
        typer.echo(
            privacy_service()
            .add_exclusion(rule, idempotency_key=f"cli-{rule.rule_id}")
            .model_dump_json()
        )

    @exclude.command("folder")
    def privacy_exclude_folder(path: str) -> None:
        rule = PrivacyRule(rule_type=PrivacyRuleType.FOLDER, pattern=path)
        typer.echo(
            privacy_service()
            .add_exclusion(rule, idempotency_key=f"cli-{rule.rule_id}")
            .model_dump_json()
        )

    @privacy.command("capture")
    def privacy_capture(
        category: CaptureCategory = CaptureCategory.DEVICE_METADATA,
        application: str | None = typer.Option(default=None),
    ) -> None:
        result = privacy_service().capture(
            CaptureRequest(
                category=category,
                payload={"application": application} if application else {},
                context=CaptureContext(application=application),
            ),
            idempotency_key=f"cli-capture-{category.value}",
        )
        typer.echo(result.model_dump_json())

    @privacy.command("history")
    def privacy_history() -> None:
        for record in privacy_service().history():
            typer.echo(record.model_dump_json())

    @privacy.command("export-history")
    def privacy_export_history() -> None:
        typer.echo(privacy_service().export_history())

    @privacy.command("delete-history")
    def privacy_delete_history() -> None:
        count = privacy_service().delete_history(idempotency_key="cli-delete-history")
        typer.echo(str(count))

    privacy.add_typer(incognito, name="incognito")
    privacy.add_typer(exclude, name="exclude")
    app.add_typer(models, name="models")
    app.add_typer(device, name="device")
    app.add_typer(learning, name="learning")
    app.add_typer(privacy, name="privacy")
    app.add_typer(interaction, name="interaction")
    app.add_typer(demonstrate, name="demonstrate")
    app.add_typer(activity, name="activity")
    app.add_typer(workflow, name="workflow")
    app.add_typer(apps, name="apps")
    app.add_typer(visual, name="visual")
    app.add_typer(mining, name="mining")
    app.add_typer(actions, name="actions")
    app.add_typer(assist, name="assist")
    app.add_typer(adapters, name="adapters")
    return app


app = create_app()
