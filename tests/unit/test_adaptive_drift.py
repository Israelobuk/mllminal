from mllminal.learning.adaptive_contracts import AdaptiveExecutionDecision
from mllminal.learning.drift import BehavioralDriftDetector


def _decision(index: int, *, shadow_changed: bool) -> AdaptiveExecutionDecision:
    return AdaptiveExecutionDecision(
        decision_id=f"decision-{index}",
        workflow_run_id=f"run-{index}",
        workflow_step_id="step-1",
        application_profile_id="profile-1",
        abstract_action="control.invoke",
        target_signature="automation_id:target",
        selected_backend="windows.uia",
        deterministic_selected_backend="windows.uia",
        advisory_scores={},
        shadow_policy={"shadow": True},
        shadow_selected_backend="local.vision" if shadow_changed else "windows.uia",
        shadow_rank_changed=shadow_changed,
        policy_version="deterministic-profile-policy-v1",
        decision_reason="test",
        execution_outcome="failed",
        verification_outcome="failed",
    )


def test_behavioral_drift_report_recommends_offline_retraining_only() -> None:
    report = BehavioralDriftDetector(
        minimum_observations=3,
        failure_rate_threshold=0.5,
        shadow_rank_change_threshold=0.5,
    ).assess([_decision(index, shadow_changed=True) for index in range(4)])

    assert report.drift_detected is True
    assert report.retraining_recommended is True
    assert report.automatic_retraining_enabled is False
    assert report.automatic_promotion_enabled is False
    assert report.failure_rate == 1.0
    assert report.shadow_rank_change_rate == 1.0
    assert "failure_rate" in report.reasons
    assert "shadow_rank_change_rate" in report.reasons


def test_behavioral_drift_report_stays_quiet_below_minimum_observations() -> None:
    report = BehavioralDriftDetector(minimum_observations=3).assess(
        [_decision(1, shadow_changed=True)]
    )

    assert report.drift_detected is False
    assert report.retraining_recommended is False
    assert report.reasons == ()
