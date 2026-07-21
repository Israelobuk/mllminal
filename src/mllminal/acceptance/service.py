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
    CapabilityReadiness,
    ReadinessClass,
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
            "readiness": [item.model_dump(mode="json") for item in self.readiness()],
            "automatic_email_send": False,
            "real_windows_acceptance_required": True,
        }

    @staticmethod
    def readiness() -> list[CapabilityReadiness]:
        groups = (
            (
                (
                    "windows.process",
                    "windows.foreground",
                    "windows.uia",
                    "windows.idle",
                    "windows.input",
                ),
                ReadinessClass.BETA,
                "src/mllminal/device/windows_adapters.py",
                "Native Windows metadata path is implemented; "
                "clean-session acceptance is still required.",
                True,
            ),
            (
                (
                    "observation.pause_resume",
                    "observation.emergency_stop",
                ),
                ReadinessClass.BETA,
                "src/mllminal/device/observer.py",
                "Lifecycle controls are implemented and require live-session evidence.",
                True,
            ),
            (
                (
                    "demonstration.start",
                    "demonstration.capture",
                    "demonstration.stop",
                    "demonstration.review",
                    "demonstration.label",
                ),
                ReadinessClass.PROTOTYPE,
                "src/mllminal/demonstration/service.py",
                "Typed demonstration state exists; a real weekly-report "
                "review and labeling run is not recorded.",
                True,
            ),
            (
                (
                    "vision.active_window_capture",
                    "vision.bounded_application",
                    "vision.user_selected_region",
                    "vision.verification_frame",
                    "vision.demonstration_fallback",
                ),
                ReadinessClass.BETA,
                "src/mllminal/verification/runtime.py",
                "Bounded local capture and cleanup are implemented; "
                "live privacy acceptance is required.",
                True,
            ),
            (
                (
                    "vision.ocr",
                    "vision.anchor_matching",
                    "vision.dialog_detection",
                    "vision.busy_state_detection",
                    "vision.error_banner_detection",
                ),
                ReadinessClass.PROTOTYPE,
                "src/mllminal/verification/service.py",
                "Provider availability is optional and no clean-machine "
                "OCR measurement is recorded.",
                True,
            ),
            (
                (
                    "filesystem.list",
                    "filesystem.inspect",
                    "filesystem.find_latest",
                    "filesystem.exists",
                    "filesystem.hash",
                    "explorer.open_folder",
                    "explorer.select_file",
                ),
                ReadinessClass.BETA,
                "src/mllminal/apps/filesystem.py",
                "Confinement and verification are implemented; "
                "live Explorer acceptance is required.",
                True,
            ),
            (
                (
                    "filesystem.create_folder",
                    "filesystem.rename",
                    "filesystem.copy",
                    "filesystem.move",
                    "filesystem.delete_to_recycle_bin",
                    "filesystem.restore",
                ),
                ReadinessClass.BETA,
                "src/mllminal/apps/filesystem.py",
                "Reversible mutation and independent verification are "
                "implemented; live evidence is required.",
                True,
            ),
            (
                (
                    "spreadsheet.inspect",
                    "spreadsheet.export_pdf",
                    "spreadsheet.verify_output",
                    "email.create_draft",
                    "email.set_recipients",
                    "email.set_subject",
                    "email.set_body",
                    "email.attach_file",
                    "email.verify_draft",
                    "provider.discovery",
                    "provider.resolution",
                ),
                ReadinessClass.BETA,
                "src/mllminal/providers",
                "Abstract capabilities resolve through detected native, browser, bundled, "
                "portable, or manual providers. Required acceptance is capability-level; "
                "provider selection must remain visible and no credentials may be extracted.",
                True,
            ),
            (
                (
                    "browser.extension",
                    "browser.native_bridge",
                    "browser.domain_permission",
                    "browser.security_page_block",
                ),
                ReadinessClass.PROTOTYPE,
                "packaging/browser-extension",
                "The signed-in browser path is implemented as a permissioned semantic-DOM seam; "
                "browser installation and live domain acceptance remain manual.",
                True,
            ),
            (
                (
                    "excel.detect",
                    "excel.open_workbook",
                    "excel.list_sheets",
                    "excel.inspect_metadata",
                    "excel.select_sheet",
                    "excel.save_copy",
                    "excel.export_pdf",
                    "excel.close_workbook",
                    "excel.verify_output",
                ),
                ReadinessClass.DEFERRED,
                "src/mllminal/apps/adapters.py",
                "Optional Excel-specific provider test deferred: this machine has no classic "
                "Excel acceptance surface. This does not block provider-neutral completion.",
                False,
            ),
            (
                (
                    "email.detect_client",
                    "email.create_draft",
                    "email.set_recipients",
                    "email.set_subject",
                    "email.set_body",
                    "email.attach_file",
                    "email.verify_draft",
                ),
                ReadinessClass.DEFERRED,
                "src/mllminal/apps/adapters.py",
                "Optional classic-Outlook-specific provider test deferred: this machine has no "
                "classic Outlook acceptance surface. Browser and manual draft paths remain valid.",
                False,
            ),
            (
                (
                    "workflow.compiler",
                    "workflow.variable_inference",
                ),
                ReadinessClass.PROTOTYPE,
                "src/mllminal/compiler/service.py",
                "Deterministic compilation exists; three real "
                "demonstrations remain an acceptance gate.",
                True,
            ),
            (
                (
                    "workflow.repair",
                    "workflow.recovery",
                    "workflow.versioning",
                ),
                ReadinessClass.PROTOTYPE,
                "src/mllminal/repair/service.py",
                "Explicit repair proposals and versions exist; live "
                "failure-and-recovery evidence is required.",
                True,
            ),
            (
                (
                    "daemon.api",
                    "daemon.cli",
                    "daemon.websocket_events",
                ),
                ReadinessClass.BETA,
                "src/mllminal/daemon/api.py",
                "Authenticated local control surfaces are implemented and covered by remote CI.",
                True,
            ),
            (
                (
                    "desktop.connected_client",
                    "desktop.cli_state_sync",
                    "desktop.emergency_stop",
                ),
                ReadinessClass.BETA,
                "src/mllminal/client/api.py",
                "Connected client is implemented; live desktop/CLI synchronization remains manual.",
                True,
            ),
            (
                (
                    "packaging.installer",
                    "packaging.startup",
                    "packaging.uninstall",
                    "packaging.diagnostics",
                ),
                ReadinessClass.PROTOTYPE,
                "packaging/windows/MLLminal.iss",
                "Installer sources exist; clean install/uninstall and "
                "artifact review remain required.",
                True,
            ),
            (
                (
                    "hardware.cpu_memory_gpu",
                    "hardware.windows_version",
                    "hardware.uia",
                    "hardware.ocr",
                    "hardware.model_availability",
                ),
                ReadinessClass.BETA,
                "src/mllminal/hardware/service.py",
                "Detection is local and non-invasive; model provisioning remains explicit.",
                True,
            ),
            (
                (
                    "privacy.secure_input_suppression",
                    "privacy.local_only_boundary",
                ),
                ReadinessClass.BETA,
                "docs/productization/security-model.md",
                "Code-level controls exist; clean adversarial deployment review remains required.",
                True,
            ),
            (
                ("ci.fake_adapter_contracts",),
                ReadinessClass.FIXTURE_ONLY,
                "tests",
                "Deterministic fake adapters are for CI and cannot "
                "substitute for real Windows acceptance.",
                False,
            ),
            (
                ("email.send",),
                ReadinessClass.DEFERRED,
                "src/mllminal/apps/adapters.py",
                "Intentionally unsupported. Product acceptance must "
                "never send email automatically.",
                False,
            ),
            (
                ("real_windows_weekly_report_acceptance",),
                ReadinessClass.DEFERRED,
                "docs/productization/acceptance-results.md",
                "The global product goal is not blocked by missing desktop applications. "
                "Only Excel-specific and classic-Outlook-specific provider evidence is deferred; "
                "capability-level acceptance may complete with available fallbacks.",
                True,
            ),
        )
        return [
            CapabilityReadiness(
                capability=name,
                classification=classification,
                evidence=[evidence],
                manual_evidence_required=manual,
                note=note,
            )
            for names, classification, evidence, note, manual in groups
            for name in names
        ]

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
