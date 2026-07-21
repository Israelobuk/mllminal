"""Deterministic learning of privacy-approved application interaction profiles."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from mllminal.contracts import new_id, utc_now
from mllminal.device.contracts import NormalizedDeviceEvent
from mllminal.interaction.contracts import InteractionEvent
from mllminal.learning.profile_contracts import (
    ApplicationInteractionProfile,
    BackendOutcomeRequest,
    BackendReliabilityRecord,
    BackendResolution,
    ProfileBackendChoice,
    ProfileControl,
    ProfileExperienceRequest,
    ProfileExperienceType,
    ProfileLearningExperience,
    ProfileOutcome,
    ProfileReliabilityScore,
)
from mllminal.learning.replay import LearningRepository

INTERACTION_BACKEND_HIERARCHY = (
    "native.provider",
    "browser.bridge",
    "windows.uia",
    "keyboard.shortcut",
    "local.vision",
    "relative.pointer",
)

_SENSITIVE_MARKERS = (
    "password",
    "cookie",
    "token",
    "secret",
    "recovery",
    "private key",
    "payment",
    "credential",
)
_SAFE_LABEL = re.compile(r"^[A-Za-z0-9 _.:+/#()\[\]-]{1,128}$")


class ApplicationInteractionProfileService:
    """Update durable profiles and advisory backend evidence without raw content."""

    def __init__(
        self,
        repository: LearningRepository,
        *,
        observation_allowed: Callable[[], bool] | None = None,
    ) -> None:
        self.repository = repository
        self.observation_allowed = observation_allowed

    def observe_device_event(
        self, event: NormalizedDeviceEvent
    ) -> ApplicationInteractionProfile | None:
        if self.observation_allowed is not None and not self.observation_allowed():
            return None
        if (
            event.event_type == "capture.rejected"
            or event.application is None
            or (event.control is not None and event.control.secure)
        ):
            return None
        if self.repository.profile_event_seen(event.event_id):
            return self._profile_for_application(event.application.process_name)
        application = event.application
        profile = self._profile_for_application(application.process_name)
        identity_key = self._identity_key(application.process_name, application.publisher)
        profile = self._apply_observation(
            profile,
            identity_key=identity_key,
            executable_name=self._executable_name(
                application.executable_path, application.process_name
            ),
            executable_path=application.executable_path,
            window_class=(event.window.window_class if event.window else None),
            window_title=(event.window.title_classification if event.window else None),
            control=(
                event.control.model_dump(mode="json")
                if event.control and not event.control.secure
                else None
            ),
            shortcut=str(event.metadata.get("shortcut"))
            if event.metadata.get("shortcut")
            else None,
            event_type=event.event_type,
            source=event.source,
            visual_anchor=(
                str(event.metadata.get("category"))
                if event.source.startswith("windows.vision") and event.metadata.get("category")
                else None
            ),
        )
        saved = self.repository.save_interaction_profile(profile, identity_key=identity_key)
        self.repository.mark_profile_event(event.event_id, saved.profile_id)
        return saved

    def observe_interaction(self, event: InteractionEvent) -> ApplicationInteractionProfile | None:
        if event.target is None or self._event_is_sensitive(event):
            return None
        if self.repository.profile_event_seen(event.id):
            return self._profile_for_application(event.target.application)
        application = event.target.application
        profile = self._profile_for_application(application)
        identity_key = self._identity_key(application, None)
        shortcut = event.shortcut
        control = None
        if event.target.control_role or event.target.control_name or event.target.automation_id:
            control = {
                "control_type": event.target.control_role or "unknown",
                "name": event.target.control_name,
                "automation_id": event.target.automation_id,
                "class_name": "unknown",
                "secure": False,
            }
        saved = self.repository.save_interaction_profile(
            self._apply_observation(
                profile,
                identity_key=identity_key,
                executable_name=application,
                executable_path=None,
                window_class=None,
                window_title=event.target.window,
                control=control,
                shortcut=shortcut,
                event_type=event.kind.value,
                source="interaction",
                visual_anchor=None,
            ),
            identity_key=identity_key,
        )
        self.repository.mark_profile_event(event.id, saved.profile_id)
        return saved

    def record_backend_outcome(
        self, request: BackendOutcomeRequest, *, idempotency_key: str
    ) -> BackendReliabilityRecord:
        profile = self.repository.get_interaction_profile(request.profile_id)
        existing_experience = self.repository.get_profile_experience_by_idempotency(idempotency_key)
        existing = self.repository.get_backend_reliability(
            request.profile_id,
            request.abstract_action,
            request.backend,
            request.target_type,
        )
        if existing_experience is not None and existing is not None:
            return existing
        attempts = (existing.attempts if existing else 0) + 1
        successes = (existing.successes if existing else 0) + int(request.succeeded)
        failures = (existing.failures if existing else 0) + int(not request.succeeded)
        verification_passes = (existing.verification_passes if existing else 0) + int(
            request.verification_passed
        )
        verification_failures = (existing.verification_failures if existing else 0) + int(
            request.succeeded and not request.verification_passed
        )
        reliability = max(
            0.0,
            min(1.0, (successes - (0.5 * verification_failures)) / max(1, attempts)),
        )
        fragility = max(
            0.0,
            min(1.0, (failures + verification_failures) / max(1, attempts * 2)),
        )
        record = BackendReliabilityRecord(
            record_id=existing.record_id if existing else new_id(),
            profile_id=request.profile_id,
            backend=request.backend,
            abstract_action=request.abstract_action,
            target_type=request.target_type,
            attempts=attempts,
            successes=successes,
            failures=failures,
            verification_passes=verification_passes,
            verification_failures=verification_failures,
            reliability=reliability,
            fragility=max(fragility, request.fragility),
            last_outcome=request.outcome,
            verification_method=request.verification_method,
            provenance=self._safe_provenance(request.provenance),
        )
        self.repository.save_backend_reliability(record)
        updated = self._update_profile_outcome(profile, record, request.succeeded)
        identity_key = self._identity_key(profile.application_identity, None)
        self.repository.save_interaction_profile(updated, identity_key=identity_key)
        experience = ProfileLearningExperience(
            profile_id=request.profile_id,
            experience_type=ProfileExperienceType.WORKFLOW_EXECUTION,
            abstract_action=request.abstract_action,
            backend=request.backend,
            target_type=request.target_type,
            verification_method=request.verification_method,
            outcome=request.outcome,
            reward=self._reward(request.outcome, request.verification_passed),
            provenance=self._safe_provenance(request.provenance),
        )
        self.repository.save_profile_experience(experience, idempotency_key=idempotency_key)
        return record

    def record_experience(
        self, request: ProfileExperienceRequest, *, idempotency_key: str
    ) -> ProfileLearningExperience:
        self.repository.get_interaction_profile(request.profile_id)
        experience = ProfileLearningExperience(
            profile_id=request.profile_id,
            experience_type=request.experience_type,
            abstract_action=request.abstract_action,
            backend=request.backend,
            target_type=request.target_type,
            verification_method=request.verification_method,
            outcome=request.outcome,
            reward=self._reward(request.outcome, request.outcome is ProfileOutcome.VERIFIED),
            provenance=self._safe_provenance(request.provenance),
        )
        saved, _ = self.repository.save_profile_experience(
            experience, idempotency_key=idempotency_key
        )
        return saved

    def list_profiles(self) -> list[ApplicationInteractionProfile]:
        return self.repository.list_interaction_profiles()

    def profile(self, profile_id: str) -> ApplicationInteractionProfile:
        return self.repository.get_interaction_profile(profile_id)

    def reliability(self, profile_id: str) -> list[BackendReliabilityRecord]:
        self.repository.get_interaction_profile(profile_id)
        return self.repository.list_backend_reliability(profile_id)

    def experiences(self, profile_id: str | None = None) -> list[ProfileLearningExperience]:
        return self.repository.list_profile_experiences(profile_id)

    def profile_summary(self, profile_id: str) -> dict[str, Any]:
        profile = self.profile(profile_id)
        return {
            "profile": profile.model_dump(mode="json"),
            "reliability": [
                record.model_dump(mode="json") for record in self.reliability(profile_id)
            ],
            "experience_count": self.repository.count_profile_experiences(profile_id),
        }

    def inspect_active(
        self, events: Iterable[NormalizedDeviceEvent]
    ) -> ApplicationInteractionProfile | None:
        for event in reversed(list(events)):
            if event.application is not None:
                return self._profile_for_application(event.application.process_name)
        return None

    def rank_backends(
        self,
        profile_id: str,
        abstract_action: str,
        target_type: str,
        available_backends: Iterable[str],
    ) -> BackendResolution:
        self.repository.get_interaction_profile(profile_id)
        records = {
            record.backend: record
            for record in self.repository.list_backend_reliability(profile_id)
            if record.abstract_action == abstract_action and record.target_type == target_type
        }
        candidates = list(dict.fromkeys(available_backends))
        hierarchy = {backend: index for index, backend in enumerate(INTERACTION_BACKEND_HIERARCHY)}

        def backend_rank(backend: str) -> tuple[float, int, int, str]:
            record = records.get(backend)
            return (
                -(record.reliability if record is not None else 0.0),
                hierarchy.get(backend, len(hierarchy)),
                -(record.attempts if record is not None else 0),
                backend,
            )

        ordered = sorted(candidates, key=backend_rank)
        scores = {
            backend: records[backend].reliability if backend in records else 0.0
            for backend in ordered
        }
        selected = ordered[0] if ordered else None
        return BackendResolution(
            profile_id=profile_id,
            abstract_action=abstract_action,
            target_type=target_type,
            selected_backend=selected,
            ordered_backends=ordered,
            reliability_by_backend=scores,
            explanation=(
                f"Selected {selected} using profile reliability evidence with the "
                "fixed interaction hierarchy as the safe tie-breaker."
                if selected
                else "No valid interaction backend is available."
            ),
        )

    def _profile_for_application(self, application: str) -> ApplicationInteractionProfile:
        identity_key = self._identity_key(application, None)
        profile = self.repository.get_interaction_profile_by_identity(identity_key)
        if profile is not None:
            return profile
        return ApplicationInteractionProfile(
            application_identity=application,
            executable_name=application,
        )

    def _apply_observation(
        self,
        profile: ApplicationInteractionProfile,
        *,
        identity_key: str,
        executable_name: str,
        executable_path: str | None,
        window_class: str | None,
        window_title: str | None,
        control: Any,
        shortcut: str | None,
        event_type: str,
        source: str,
        visual_anchor: str | None,
    ) -> ApplicationInteractionProfile:
        now = profile.last_seen_at if profile.observation_count == 0 else utc_now()
        controls = list(profile.discovered_controls)
        if control is not None:
            role = self._safe_label(control.get("control_type", "unknown")) or "unknown"
            name = self._safe_label(control.get("name"))
            automation_id = self._safe_label(control.get("automation_id"))
            class_name = self._safe_label(control.get("class_name")) or "unknown"
            index = next(
                (
                    index
                    for index, item in enumerate(controls)
                    if (automation_id and item.automation_id == automation_id)
                    or (
                        not automation_id
                        and item.control_role == role
                        and item.control_name == name
                    )
                ),
                None,
            )
            discovered = ProfileControl(
                control_role=role,
                control_name=name,
                automation_id=automation_id,
                class_name=class_name,
                observation_count=1,
                last_seen_at=now,
            )
            if index is None:
                controls.append(discovered)
            else:
                current = controls[index]
                controls[index] = current.model_copy(
                    update={
                        "observation_count": current.observation_count + 1,
                        "last_seen_at": now,
                    }
                )
        normalized_shortcut = shortcut.strip().upper() if shortcut else None
        shortcuts = self._append_unique(profile.observed_keyboard_shortcuts, normalized_shortcut)
        window_classes = self._append_unique(
            profile.window_class_patterns, self._safe_label(window_class)
        )
        windows = self._append_unique(
            profile.observed_window_titles, self._redact_window(window_title)
        )
        menus = list(profile.observed_menus_dialogs)
        if window_title and self._redact_window(window_title) == "dialog":
            menus = self._append_unique(menus, "dialog")
        if control is not None and str(control.get("control_type", "")).casefold() == "menuitem":
            menus = self._append_unique(menus, "menuitem")
        transitions = list(profile.observed_state_transitions)
        if profile.last_observed_event_type and profile.last_observed_event_type != event_type:
            transitions = self._append_unique(
                transitions, f"{profile.last_observed_event_type}->{event_type}"
            )
        stable_ids = sorted(
            {
                *profile.stable_automation_ids,
                *(
                    item.automation_id
                    for item in controls
                    if item.automation_id and item.observation_count >= 2
                ),
            }
        )
        stable_names = sorted(
            {
                *profile.stable_control_names_roles,
                *(
                    f"{item.control_role}:{item.control_name or ''}"
                    for item in controls
                    if item.observation_count >= 2
                ),
            }
        )
        support = profile.accessibility_support_level
        if source == "windows.uia" and control is not None:
            support = "ui_automation"
        elif support == "metadata_only" and source == "windows.foreground":
            support = "foreground_metadata"
        return profile.model_copy(
            update={
                "executable_name": executable_name,
                "executable_path_hash": self._path_hash(executable_path)
                or profile.executable_path_hash,
                "window_class_patterns": window_classes,
                "observed_window_titles": windows,
                "accessibility_support_level": support,
                "discovered_controls": controls,
                "stable_automation_ids": stable_ids,
                "stable_control_names_roles": stable_names,
                "observed_keyboard_shortcuts": shortcuts,
                "observed_menus_dialogs": menus,
                "visual_anchors": self._append_unique(profile.visual_anchors, visual_anchor),
                "observed_state_transitions": transitions,
                "first_seen_at": profile.first_seen_at if profile.observation_count else now,
                "last_seen_at": now,
                "observation_count": profile.observation_count + 1,
                "last_observed_event_type": event_type,
                "profile_version": profile.profile_version + 1,
            }
        )

    def _update_profile_outcome(
        self,
        profile: ApplicationInteractionProfile,
        record: BackendReliabilityRecord,
        succeeded: bool,
    ) -> ApplicationInteractionProfile:
        choice = ProfileBackendChoice(
            backend=record.backend,
            abstract_action=record.abstract_action,
            target_type=record.target_type,
            verification_method=record.verification_method,
            observation_count=1,
            last_seen_at=record.last_seen_at,
        )
        choices = (
            list(profile.successful_backend_choices)
            if succeeded
            else list(profile.failed_backend_choices)
        )
        index = next(
            (
                index
                for index, item in enumerate(choices)
                if item.backend == choice.backend
                and item.abstract_action == choice.abstract_action
                and item.target_type == choice.target_type
            ),
            None,
        )
        if index is None:
            choices.append(choice)
        else:
            choices[index] = choices[index].model_copy(
                update={"observation_count": choices[index].observation_count + 1}
            )
        scores = [
            item
            for item in profile.reliability_scores
            if not (
                item.backend == record.backend
                and item.abstract_action == record.abstract_action
                and item.target_type == record.target_type
            )
        ]
        scores.append(
            ProfileReliabilityScore(
                backend=record.backend,
                abstract_action=record.abstract_action,
                target_type=record.target_type,
                attempts=record.attempts,
                successes=record.successes,
                failures=record.failures,
                verification_passes=record.verification_passes,
                verification_failures=record.verification_failures,
                reliability=record.reliability,
                fragility=record.fragility,
                last_outcome=record.last_outcome,
                last_seen_at=record.last_seen_at,
            )
        )
        return profile.model_copy(
            update={
                "successful_backend_choices": sorted(
                    choices if succeeded else profile.successful_backend_choices,
                    key=lambda item: (item.backend, item.abstract_action, item.target_type),
                ),
                "failed_backend_choices": sorted(
                    choices if not succeeded else profile.failed_backend_choices,
                    key=lambda item: (item.backend, item.abstract_action, item.target_type),
                ),
                "reliability_scores": scores,
                "fragility_scores": scores,
                "successful_execution_count": profile.successful_execution_count + int(succeeded),
                "failed_execution_count": profile.failed_execution_count + int(not succeeded),
                "last_seen_at": record.last_seen_at,
                "profile_version": profile.profile_version + 1,
            }
        )

    @staticmethod
    def _event_is_sensitive(event: InteractionEvent) -> bool:
        if event.text_metadata is not None:
            return event.text_metadata.secure_control.value != "none"
        values = (
            [event.target.control_name or "", event.target.window or ""] if event.target else []
        )
        return any(marker in value.casefold() for value in values for marker in _SENSITIVE_MARKERS)

    @staticmethod
    def _identity_key(application: str, publisher: str | None) -> str:
        return f"{application.casefold().strip()}::{(publisher or '').casefold().strip()}"

    @staticmethod
    def _path_hash(path: str | None) -> str | None:
        return hashlib.sha256(path.casefold().encode("utf-8")).hexdigest() if path else None

    @staticmethod
    def _executable_name(path: str | None, process_name: str) -> str:
        return Path(path).name if path else process_name

    @staticmethod
    def _safe_label(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text or any(marker in text.casefold() for marker in _SENSITIVE_MARKERS):
            return None
        return text if _SAFE_LABEL.fullmatch(text) else None

    @classmethod
    def _redact_window(cls, value: str | None) -> str | None:
        safe = cls._safe_label(value)
        if safe is None:
            return None
        lowered = safe.casefold()
        if "dialog" in lowered or "#32770" in lowered:
            return "dialog"
        if "browser" in lowered or "chrome" in lowered or "edge" in lowered:
            return "browser"
        if lowered in {"document", "secure-dialog", "unknown"}:
            return lowered
        return f"title:{hashlib.sha256(safe.casefold().encode('utf-8')).hexdigest()[:12]}"

    @staticmethod
    def _append_unique(values: list[str], value: str | None) -> list[str]:
        if value and value not in values:
            return [*values, value]
        return list(values)

    @staticmethod
    def _safe_provenance(values: dict[str, Any]) -> dict[str, Any]:
        safe: dict[str, Any] = {}
        for key, value in values.items():
            normalized_key = str(key).casefold()
            if any(marker in normalized_key for marker in _SENSITIVE_MARKERS):
                continue
            if isinstance(value, bool | int | float) or (
                isinstance(value, str) and len(value) <= 128
            ):
                safe[str(key)] = value
        return safe

    @staticmethod
    def _reward(outcome: ProfileOutcome, verification_passed: bool) -> float:
        if outcome is ProfileOutcome.VERIFIED and verification_passed:
            return 3.0
        if outcome in {ProfileOutcome.SUCCEEDED, ProfileOutcome.ACCEPTED}:
            return 1.0
        if outcome is ProfileOutcome.REJECTED:
            return -1.0
        if outcome in {ProfileOutcome.FAILED, ProfileOutcome.CORRECTED}:
            return -2.0
        if outcome in {ProfileOutcome.ROLLED_BACK, ProfileOutcome.EMERGENCY_STOPPED}:
            return -2.5
        return -0.5
