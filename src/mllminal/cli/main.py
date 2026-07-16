"""Typer command-line interface for local model selection."""

import asyncio
from collections.abc import Awaitable, Callable

import typer

from mllminal.agent.ollama import OllamaClient, OllamaProviderError
from mllminal.config import ProviderConfig, ProviderConfigStore, Settings
from mllminal.learning.contracts import PolicyVersion
from mllminal.learning.evaluation import EvaluationCase
from mllminal.learning.governance import CandidateGovernanceService, PromotionApprovalError
from mllminal.learning.registry import PolicyRegistry
from mllminal.learning.replay import LearningRepository
from mllminal.learning.service import CandidateTrainingService, MinimumExperienceError

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

    app.add_typer(models, name="models")
    app.add_typer(learning, name="learning")
    return app


app = create_app()
