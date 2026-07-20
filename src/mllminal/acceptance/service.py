"""Durable acceptance checklist and security/performance boundary reporting."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mllminal.acceptance.contracts import (
    AcceptanceCheck,
    AcceptanceRecordRequest,
    AcceptanceRun,
    AcceptanceStage,
    AcceptanceState,
)

_ORDER = list(AcceptanceStage)


class ProductAcceptanceService:
    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir
        self.path.mkdir(parents=True, exist_ok=True)

    def start(self) -> AcceptanceRun:
        run = AcceptanceRun(
            state=AcceptanceState.IN_PROGRESS,
            checks=self._checks(),
        )
        self._save(run)
        return run

    def status(self) -> AcceptanceRun | None:
        runs = sorted(self.path.glob("*.json"), key=lambda item: item.stat().st_mtime)
        if not runs:
            return None
        return AcceptanceRun.model_validate_json(runs[-1].read_text(encoding="utf-8"))

    def record(self, request: AcceptanceRecordRequest) -> AcceptanceRun:
        run = self.status()
        if run is None:
            raise RuntimeError("Acceptance run has not started")
        expected_index = 0 if run.current_stage is None else _ORDER.index(run.current_stage) + 1
        stage_index = _ORDER.index(request.stage)
        if stage_index != expected_index:
            raise ValueError(
                "Acceptance stage must advance from "
                f"{_ORDER[expected_index - 1].value if expected_index else 'start'}"
            )
        checks = [item for item in run.checks if item.name != request.stage.value]
        name = request.stage.value
        checks.append(
            AcceptanceCheck(
                name=name,
                category="scenario",
                status="passed" if request.verified else "blocked",
                evidence=request.evidence,
                note=request.note,
            )
        )
        updated = run.model_copy(
            update={
                "state": AcceptanceState.IN_PROGRESS
                if request.verified
                else AcceptanceState.BLOCKED,
                "current_stage": request.stage,
                "checks": checks,
                "updated_at": datetime.now(UTC),
            }
        )
        if request.verified and request.stage is AcceptanceStage.USER_REVIEWED:
            updated = updated.model_copy(update={"state": AcceptanceState.PASSED})
        self._save(updated)
        return updated

    def security(self) -> list[AcceptanceCheck]:
        return [
            AcceptanceCheck(
                name="secure_input_suppression",
                category="security",
                status="implemented",
                note="Native secure controls suppress text metadata.",
            ),
            AcceptanceCheck(
                name="path_traversal_and_link_escape",
                category="security",
                status="implemented",
                note=(
                    "Filesystem and attachment adapters reject traversal, symlinks, and junctions."
                ),
            ),
            AcceptanceCheck(
                name="permission_and_replay_gates",
                category="security",
                status="implemented",
                note="Daemon grants, approvals, and replay authorization remain server-side.",
            ),
            AcceptanceCheck(
                name="forged_verification_and_duplicate_execution",
                category="security",
                status="implemented",
                note="Persisted idempotency and independent verification are required.",
            ),
            AcceptanceCheck(
                name="emergency_stop_and_stale_approval",
                category="security",
                status="implemented",
                note="Emergency-stop and approval state are checked before execution.",
            ),
            AcceptanceCheck(
                name="ocr_prompt_injection_and_unauthorized_client",
                category="security",
                status="manual_required",
                note="Complete on a clean Windows desktop with adversarial fixtures.",
            ),
        ]

    def performance(self) -> list[AcceptanceCheck]:
        return [
            AcceptanceCheck(
                name=name,
                category="performance",
                status="manual_required",
                note="Measure on a clean Windows environment and retain raw measurements.",
            )
            for name in (
                "idle_daemon_cpu",
                "idle_daemon_memory",
                "observation_overhead",
                "event_persistence_throughput",
                "event_stream_latency",
                "cli_startup",
                "desktop_startup",
                "workflow_preview_latency",
                "filesystem_action_latency",
                "excel_export_latency",
                "ocr_latency",
            )
        ]

    def report(self) -> dict[str, Any]:
        run = self.status()
        return {
            "scenario": run.model_dump(mode="json") if run else None,
            "security": [item.model_dump(mode="json") for item in self.security()],
            "performance": [item.model_dump(mode="json") for item in self.performance()],
            "automatic_email_send": False,
            "real_windows_acceptance_required": True,
        }

    @staticmethod
    def _checks() -> list[AcceptanceCheck]:
        return [
            AcceptanceCheck(
                name=stage.value,
                category="scenario",
                status="manual_required",
                note="Complete on a clean Windows environment with a non-sensitive test fixture.",
            )
            for stage in AcceptanceStage
        ]

    def _save(self, run: AcceptanceRun) -> None:
        path = self.path / f"{run.id}.json"
        tmp = path.with_name(path.name + ".next")
        tmp.write_text(run.model_dump_json(), encoding="utf-8", newline="")
        tmp.replace(path)
