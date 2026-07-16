from pathlib import Path

from mllminal.daemon.auth import load_or_create_token


def test_token_is_generated_once_and_persisted(tmp_path: Path) -> None:
    token_path = tmp_path / "token"

    first = load_or_create_token(token_path)
    second = load_or_create_token(token_path)

    assert first == second
    assert len(first) >= 32
    assert token_path.read_text(encoding="utf-8") == first
