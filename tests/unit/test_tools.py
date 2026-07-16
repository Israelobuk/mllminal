from pathlib import Path

import pytest

from mllminal.tools import ToolRegistry, WorkspaceBoundaryError


def test_read_text_is_confined_to_attached_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    registry = ToolRegistry()

    with pytest.raises(WorkspaceBoundaryError):
        registry.execute("project.read_text", {"path": "../secret.txt"}, workspace)


def test_project_tools_return_typed_read_only_results(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'", encoding="utf-8")
    (tmp_path / "train.py").write_text("print('train')", encoding="utf-8")
    registry = ToolRegistry()

    listing = registry.execute("project.list_files", {"path": "."}, tmp_path)
    content = registry.execute("project.read_text", {"path": "train.py"}, tmp_path)
    metadata = registry.execute("project.inspect_metadata", {}, tmp_path)

    assert listing["files"] == ["pyproject.toml", "train.py"]
    assert content["content"] == "print('train')"
    assert metadata["project_type"] == "python"
    assert registry.verify("project.inspect_metadata", metadata).succeeded is True
