"""Thin authenticated CLI commands for daemon-owned offline learning state."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import typer

from mllminal.client.api import DaemonClientError, LearningDaemonClient
from mllminal.config import Settings
from mllminal.learning.contracts import PolicyDomain

ClientFactory = Callable[[Settings], LearningDaemonClient]


def register_learning_commands(
    learning: typer.Typer,
    settings: Settings,
    client_factory: ClientFactory,
) -> None:
    """Attach daemon-backed learning groups to the existing learning CLI."""

    learning.registered_commands = [
        command
        for command in learning.registered_commands
        if getattr(command, "name", None) != "experiences"
    ]
    experiences = typer.Typer(help="List safe learning-experience projections.")
    replay = typer.Typer(help="Create and inspect immutable replay snapshots.")
    policy = typer.Typer(help="Train and explicitly govern advisory candidates.")
    worker = typer.Typer(help="Inspect or cancel daemon-owned training workers.")
    experiments = typer.Typer(help="Inspect durable offline training runs.")

    def client() -> LearningDaemonClient:
        return client_factory(settings)

    def call(operation: Callable[[LearningDaemonClient], Any]) -> Any:
        try:
            return asyncio.run(operation(client()))
        except PermissionError as error:
            typer.echo(f"Authentication failed: {error}")
        except KeyError as error:
            typer.echo(f"Invalid ID: {error.args[0]}")
        except DaemonClientError as error:
            typer.echo(f"Daemon error [{error.code}]: {error.message}")
        except httpx.HTTPStatusError as error:
            try:
                body = error.response.json()
            except ValueError:
                body = {}
            if isinstance(body, dict) and body.get("code") and body.get("message"):
                typer.echo(f"Daemon error [{body['code']}]: {body['message']}")
            else:
                typer.echo(f"Daemon request failed: {error.response.status_code}")
        except (httpx.RequestError, OSError) as error:
            typer.echo(f"Daemon unavailable: {error}")
        raise typer.Exit(code=1)

    def emit(payload: Any, summary: Any, json_output: bool) -> None:
        typer.echo(json.dumps(summary, sort_keys=True))

    def safe_experience(item: dict[str, Any]) -> dict[str, Any]:
        return {
            key: item[key]
            for key in ("experience_id", "profile_id", "experience_type", "outcome", "created_at")
            if key in item
        }

    def safe_snapshot(item: dict[str, Any]) -> dict[str, Any]:
        return {
            key: item[key]
            for key in (
                "snapshot_id",
                "policy_domain",
                "experience_count",
                "dataset_digest",
                "split_digest",
                "random_seed",
                "status",
                "created_at",
            )
            if key in item
        }

    def safe_run(item: dict[str, Any]) -> dict[str, Any]:
        return {
            key: item[key]
            for key in (
                "id",
                "status",
                "lifecycle_stage",
                "eligible_experience_count",
                "created_at",
                "completed_at",
            )
            if key in item
        }

    def safe_policy(item: dict[str, Any]) -> dict[str, Any]:
        return {
            key: item[key]
            for key in (
                "id",
                "name",
                "policy_domain",
                "lifecycle",
                "training_run_id",
                "replay_snapshot_id",
                "created_at",
            )
            if key in item
        }

    def training_summary(item: dict[str, Any]) -> dict[str, Any]:
        snapshot = item.get("snapshot")
        if not isinstance(snapshot, dict):
            snapshot = {}
        run = item.get("training_run")
        if not isinstance(run, dict):
            run = {}
        candidate = item.get("candidate")
        if not isinstance(candidate, dict):
            candidate = {}
        worker_data = item.get("worker")
        if not isinstance(worker_data, dict):
            worker_data = {}
        return {
            "worker_job_id": worker_data.get("job_id")
            or worker_data.get("worker_job_id")
            or worker_data.get("worker_pid"),
            "worker_status": worker_data.get("status"),
            "training_run_id": run.get("id"),
            "training_status": run.get("status"),
            "candidate_policy_id": candidate.get("id"),
            "candidate_lifecycle": candidate.get("lifecycle"),
            "candidate_name": candidate.get("name"),
            "snapshot_id": snapshot.get("snapshot_id"),
            "policy_domain": snapshot.get("policy_domain") or candidate.get("policy_domain"),
        }

    @experiences.command("list")
    def experiences_list(
        profile_id: str | None = typer.Option(None, "--profile-id"),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        result = call(lambda value: value.learning_experiences(profile_id))
        summaries = [safe_experience(item) for item in result]
        if json_output:
            emit(result, summaries, True)
        else:
            for item in summaries:
                typer.echo(" ".join(f"{key}={value}" for key, value in item.items()))

    @experiences.command("show")
    def experiences_show(
        experience_id: str,
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        result = call(lambda value: value.learning_experience(experience_id))
        summary = safe_experience(result)
        if json_output:
            emit(result, summary, True)
        else:
            for key, value in summary.items():
                typer.echo(f"{key}: {value}")

    @replay.command("create")
    def replay_create(
        domain: PolicyDomain = typer.Option(..., "--domain"),  # noqa: B008
        seed: int = typer.Option(42, min=0),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        payload = {"policy_domain": domain.value, "seed": seed}
        result = call(
            lambda value: value.replay_create(
                payload, idempotency_key=f"cli-learning-replay-create-{domain.value}-{seed}"
            )
        )
        summary = safe_snapshot(result)
        if json_output:
            emit(result, summary, True)
        else:
            for key, value in summary.items():
                typer.echo(f"{key}: {value}")

    @replay.command("list")
    def replay_list(json_output: bool = typer.Option(False, "--json")) -> None:
        result = call(lambda value: value.replay_snapshots())
        summaries = [safe_snapshot(item) for item in result]
        if json_output:
            emit(result, summaries, True)
        else:
            for item in summaries:
                typer.echo(" ".join(f"{key}={value}" for key, value in item.items()))

    @replay.command("show")
    def replay_show(snapshot_id: str, json_output: bool = typer.Option(False, "--json")) -> None:
        result = call(lambda value: value.replay_snapshot(snapshot_id))
        summary = safe_snapshot(result)
        if json_output:
            emit(result, summary, True)
        else:
            for key, value in summary.items():
                typer.echo(f"{key}: {value}")

    @policy.command("train")
    def policy_train(
        domain: PolicyDomain = typer.Option(..., "--domain"),  # noqa: B008
        seed: int = typer.Option(42, min=0),
        epochs: int = typer.Option(20, min=1, max=100),
        learning_rate: float = typer.Option(0.01, min=0.000001, max=1.0),
        hidden_size: int = typer.Option(16, min=1, max=128),
        cpu_threads: int = typer.Option(1, min=1, max=8),
        timeout_seconds: float = typer.Option(30.0, min=1.0, max=300.0),
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        payload = {
            "policy_domain": domain.value,
            "seed": seed,
            "epochs": epochs,
            "learning_rate": learning_rate,
            "hidden_size": hidden_size,
            "cpu_threads": cpu_threads,
            "timeout_seconds": timeout_seconds,
        }
        result = call(
            lambda value: value.offline_train(
                payload,
                idempotency_key=f"cli-learning-policy-train-{domain.value}",
            )
        )
        summary = training_summary(result)
        if json_output:
            emit(result, summary, True)
        else:
            for label, key in (
                ("Worker job ID", "worker_job_id"),
                ("Worker status", "worker_status"),
                ("Training run ID", "training_run_id"),
                ("Training status", "training_status"),
                ("Candidate policy ID", "candidate_policy_id"),
                ("Candidate lifecycle", "candidate_lifecycle"),
                ("Snapshot ID", "snapshot_id"),
                ("Policy domain", "policy_domain"),
            ):
                if summary.get(key) is not None:
                    typer.echo(f"{label}: {summary[key]}")

    @policy.command("status")
    def policy_status(
        candidate_or_run_id: str, json_output: bool = typer.Option(False, "--json")
    ) -> None:
        result = call(lambda value: value.policy_status(candidate_or_run_id))
        summary = safe_policy(result) if "lifecycle" in result else safe_run(result)
        if json_output:
            emit(result, summary, True)
        else:
            for key, value in summary.items():
                typer.echo(f"{key}: {value}")

    @policy.command("evaluate")
    def policy_evaluate(
        candidate_id: str, json_output: bool = typer.Option(False, "--json")
    ) -> None:
        result = call(
            lambda value: value.policy_evaluate(
                candidate_id, idempotency_key=f"cli-learning-policy-evaluate-{candidate_id}"
            )
        )
        if json_output:
            emit(result, result, True)
        else:
            typer.echo(f"Evaluation report ID: {result.get('id', 'unknown')}")
            typer.echo(
                f"Status: {'eligible for promotion' if result.get('passed') else 'rejected'}"
            )

    @policy.command("compare")
    def policy_compare(
        candidate_id: str, json_output: bool = typer.Option(False, "--json")
    ) -> None:
        result = call(lambda value: value.policy_compare(candidate_id))
        if json_output:
            emit(result, result, True)
        else:
            for key, value in result.items():
                typer.echo(f"{key}: {value}")

    @policy.command("promote")
    def policy_promote(
        candidate_id: str, json_output: bool = typer.Option(False, "--json")
    ) -> None:
        result = call(
            lambda value: value.policy_promote(
                candidate_id, idempotency_key=f"cli-learning-policy-promote-{candidate_id}"
            )
        )
        summary = safe_policy(result)
        if json_output:
            emit(result, summary, True)
        else:
            typer.echo(f"Policy: {summary.get('id', candidate_id)}")
            typer.echo(f"State: {summary.get('lifecycle', 'ACTIVE')}")

    @policy.command("rollback")
    def policy_rollback(policy_id: str, json_output: bool = typer.Option(False, "--json")) -> None:
        result = call(
            lambda value: value.policy_rollback(
                policy_id, idempotency_key=f"cli-learning-policy-rollback-{policy_id}"
            )
        )
        if json_output:
            emit(result, result, True)
        else:
            typer.echo(f"Rollback record ID: {result.get('id', 'unknown')}")
            typer.echo(f"State: rolled back to {result.get('to_policy_version_id', 'unknown')}")

    @policy.command("active")
    def policy_active(
        domain: PolicyDomain = typer.Option(..., "--domain"),  # noqa: B008
        json_output: bool = typer.Option(False, "--json"),
    ) -> None:
        result = call(lambda value: value.active_policy(domain.value))
        summary = safe_policy(result)
        if json_output:
            emit(result, summary, True)
        else:
            for key, value in summary.items():
                typer.echo(f"{key}: {value}")

    @worker.command("status")
    def worker_status(job_id: str, json_output: bool = typer.Option(False, "--json")) -> None:
        result = call(lambda value: value.worker_status(job_id))
        if json_output:
            emit(result, result, True)
        else:
            for key, value in result.items():
                if key in {
                    "job_id",
                    "policy_domain",
                    "status",
                    "training_run_id",
                    "candidate_policy_id",
                    "worker_status",
                    "failure_reason",
                }:
                    typer.echo(f"{key}: {value}")

    @worker.command("cancel")
    def worker_cancel(job_id: str, json_output: bool = typer.Option(False, "--json")) -> None:
        result = call(
            lambda value: value.worker_cancel(
                job_id, idempotency_key=f"cli-learning-worker-cancel-{job_id}"
            )
        )
        if json_output:
            emit(result, result, True)
        else:
            typer.echo(f"Worker job ID: {result.get('job_id', job_id)}")
            typer.echo(f"State: {result.get('status', 'cancelled')}")

    @experiments.command("list")
    def experiments_list(json_output: bool = typer.Option(False, "--json")) -> None:
        result = call(lambda value: value.learning_runs())
        summaries = [safe_run(item) for item in result]
        if json_output:
            emit(result, summaries, True)
        else:
            for item in summaries:
                typer.echo(" ".join(f"{key}={value}" for key, value in item.items()))

    @experiments.command("show")
    def experiments_show(run_id: str, json_output: bool = typer.Option(False, "--json")) -> None:
        result = call(lambda value: value.learning_run(run_id))
        summary = safe_run(result)
        if json_output:
            emit(result, summary, True)
        else:
            for key, value in summary.items():
                typer.echo(f"{key}: {value}")

    learning.add_typer(experiences, name="experiences")
    learning.add_typer(replay, name="replay")
    learning.add_typer(policy, name="policy")
    learning.add_typer(worker, name="worker")
    learning.add_typer(experiments, name="experiments")
