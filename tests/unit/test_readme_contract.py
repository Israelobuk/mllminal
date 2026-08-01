from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_readme_is_a_product_page_with_current_boundaries() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8-sig")

    required = (
        "private, local workflow-intelligence system",
        "Mil is the conversational interface",
        "implemented",
        "optional",
        "experimental",
        "deferred",
        "unsupported",
        "SQLAlchemy 2 + Alembic",
        "PyTorch",
        "scikit-learn",
        "LangGraph",
        "Ollama + Qwen",
        "MLflow",
        "DuckDB + Parquet",
        "no MLLminal cloud offloading",
        "no password or credential capture",
        "no unrestricted shell execution",
        "emergency stop remains authoritative",
        "mllminal doctor",
        "mllminal mil",
        "mllminal tui",
        "mllminal install purge-data --confirm MLLMINAL",
        "Technical preview",
        "```mermaid",
    )
    lowered = readme.casefold()
    for phrase in required:
        assert phrase.casefold() in lowered

    assert "currently implementing the Windows-first foundation slice" not in readme
    assert "Tauri/React" not in readme
    assert "primarily Office automation" not in readme
    installation = readme.split("## Windows installation", 1)[1].split(
        "## Upgrade, repair, and uninstall", 1
    )[0]
    assert "Download the Windows setup executable" in installation
    assert "Double-click it" in installation
    assert "Start Menu" in installation
    assert "mllminal doctor" not in installation
    assert "/VERYSILENT /NORESTART" in readme
    assert "Close setup at the Ready page" in readme


def test_related_docs_use_cli_first_product_framing() -> None:
    productization = (ROOT / "docs/productization/cli-tui-client.md").read_text(
        encoding="utf-8-sig"
    )
    foundation_path = ROOT / "docs/superpowers/specs/2026-07-16-mllminal-foundation-design.md"
    foundation = foundation_path.read_text(encoding="utf-8-sig")

    assert "CLI-first product" in productization
    assert "installed product has no frontend build prerequisite" in productization
    assert "current product layers" in foundation


def test_install_docs_match_hidden_diagnostics_launcher() -> None:
    paths = (
        ROOT / "README.md",
        ROOT / "packaging/windows/README.md",
        ROOT / "docs/superpowers/specs/2026-07-31-true-one-click-windows-installation-design.md",
        ROOT / "docs/superpowers/plans/2026-07-31-true-one-click-windows-installation.md",
    )
    documents = [path.read_text(encoding="utf-8-sig") for path in paths]

    for document in documents:
        assert "doctor --json" in document
        assert "powershell.exe -NoExit" not in document
        assert "readable `mllminal doctor` terminal" not in document

    assert "doctor-shortcut.json" in documents[0]
    assert "doctor-shortcut.json" in documents[1]
    assert "doctor-shortcut.json" in documents[2]
