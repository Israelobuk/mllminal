"""Local daemon token management."""

import contextlib
import os
import secrets
from pathlib import Path


def load_or_create_token(path: Path) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(token, encoding="utf-8")
    with contextlib.suppress(OSError):
        os.chmod(temporary, 0o600)
    temporary.replace(path)
    return token
