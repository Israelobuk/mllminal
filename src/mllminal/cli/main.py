"""Typer command-line interface for local model selection."""

import asyncio
from collections.abc import Awaitable, Callable

import typer

from mllminal.agent.ollama import OllamaClient, OllamaProviderError
from mllminal.config import ProviderConfig, ProviderConfigStore, Settings

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

    app.add_typer(models, name="models")
    return app


app = create_app()
