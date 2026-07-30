from pathlib import Path

from mllminal.acceptance.service import ProductAcceptanceService


def test_cross_provider_matrix_covers_generic_capabilities_and_safety_invariants(
    tmp_path: Path,
) -> None:
    service = ProductAcceptanceService(tmp_path)

    matrix = service.cross_provider_matrix()
    by_capability = {entry.capability: entry for entry in matrix}

    assert {
        "application.inspect_state",
        "control.invoke",
        "document.export",
        "file.move",
        "table.read",
        "draft.create",
    } <= set(by_capability)
    assert all(entry.provider_kinds for entry in matrix)
    assert all(entry.requires_independent_verification for entry in matrix)
    assert all(entry.external_submission_allowed is False for entry in matrix)
    assert by_capability["control.invoke"].approval_required is True
    assert by_capability["document.export"].approval_required is True
    assert by_capability["application.inspect_state"].approval_required is False
    assert "email.send" not in by_capability
    assert all(
        name not in entry.capability.casefold() for entry in matrix for name in ("excel", "outlook")
    )

    report = service.report()
    assert len(report["cross_provider_matrix"]) == len(matrix)
