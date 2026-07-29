from mllminal.learning.adaptive_contracts import AdaptiveExecutionDecision
from mllminal.learning.metrics import summarize_backend_outcomes


def _decision(
    decision_id: str,
    *,
    selected: str | None,
    deterministic: str | None,
    advisory_changed: bool,
    shadow: bool,
    shadow_changed: bool,
    execution: str | None,
    verification: str | None,
) -> AdaptiveExecutionDecision:
    return AdaptiveExecutionDecision(
        decision_id=decision_id,
        workflow_run_id=decision_id,
        workflow_step_id="step-1",
        application_profile_id="profile-1",
        abstract_action="control.invoke",
        target_signature="automation_id:target",
        selected_backend=selected,
        deterministic_selected_backend=deterministic,
        advisory_changed_selection=advisory_changed,
        deterministic_scores={"windows.uia": 0.8, "local.vision": 0.2},
        advisory_scores={"windows.uia": 0.2, "local.vision": 0.9} if advisory_changed else {},
        combined_scores={"windows.uia": 0.7, "local.vision": 0.8},
        shadow_policy={"shadow": True} if shadow else {},
        shadow_selected_backend="local.vision" if shadow_changed else selected,
        shadow_rank_changed=shadow_changed,
        policy_version="deterministic-profile-policy-v1",
        decision_reason="test",
        execution_outcome=execution,
        verification_outcome=verification,
    )


def test_backend_outcome_metrics_attribute_live_and_shadow_influence() -> None:
    metrics = summarize_backend_outcomes(
        [
            _decision(
                "one",
                selected="windows.uia",
                deterministic="windows.uia",
                advisory_changed=False,
                shadow=True,
                shadow_changed=True,
                execution="succeeded",
                verification="passed",
            ),
            _decision(
                "two",
                selected="local.vision",
                deterministic="windows.uia",
                advisory_changed=True,
                shadow=True,
                shadow_changed=False,
                execution="failed",
                verification="failed",
            ),
            _decision(
                "three",
                selected=None,
                deterministic=None,
                advisory_changed=False,
                shadow=False,
                shadow_changed=False,
                execution=None,
                verification=None,
            ),
        ]
    )

    assert metrics.decision_count == 3
    assert metrics.outcome_count == 2
    assert metrics.execution_success_count == 1
    assert metrics.verification_pass_count == 1
    assert metrics.active_advisory_decision_count == 1
    assert metrics.active_advisory_influence_count == 1
    assert metrics.shadow_evaluation_count == 2
    assert metrics.shadow_rank_change_count == 1
    assert metrics.shadow_rank_change_rate == 0.5
    assert metrics.outcome_coverage == 2 / 3
