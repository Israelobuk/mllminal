from pathlib import Path


def test_learning_package_modules_exist() -> None:
    package = Path("src/mllminal/learning")

    assert {path.name for path in package.glob("*.py")} == {
        "__init__.py",
        "contracts.py",
        "features.py",
        "rewards.py",
    }
