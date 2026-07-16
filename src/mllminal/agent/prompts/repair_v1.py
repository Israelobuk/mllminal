"""Constrained repair instructions, version 1."""


def repair_message(validation_error: str) -> str:
    return (
        "Repair the previous response. Return only a valid JSON envelope using supplied tools "
        "and permissions. Validation error: "
        f"{validation_error}"
    )
