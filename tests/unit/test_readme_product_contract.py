from pathlib import Path

README = Path(__file__).parents[2] / "README.md"


def test_readme_starts_with_simple_product_install_and_commands() -> None:
    text = README.read_text(encoding="utf-8")

    assert text.startswith("# MLLminal")
    assert "MLLminal is a private, local workflow-intelligence system" in text
    assert "## Install for Windows" in text
    assert "1. Download the Windows installer." in text
    assert "5. Start Mil:" in text
    assert "mllminal mil" in text
    assert "mllminal chat" in text
    assert "mllminal run" in text
    assert "mllminal apps" in text
    assert "mllminal doctor" in text


def test_readme_explains_product_boundaries_and_technology_roles() -> None:
    text = README.read_text(encoding="utf-8")

    for phrase in (
        "Mil is the conversational interface",
        "typed capabilities",
        "independently verified",
        "SQLAlchemy 2 + Alembic",
        "PyTorch",
        "scikit-learn",
        "LangGraph",
        "Ollama + Qwen",
        "MLflow",
        "DuckDB + Parquet",
        "Deterministic safety filtering occurs before learned ranking",
        "no automatic policy promotion",
        "technical preview",
    ):
        assert phrase in text

    for stale in ("Tauri", "React", "active policy integration is still unimplemented"):
        assert stale.casefold() not in text.casefold()
