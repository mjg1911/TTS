from __future__ import annotations

import os
from pathlib import Path
import secrets
import tempfile
from typing import Optional


_MIN_TOKEN_LENGTH = 40


def browser_token_path(appdata: Optional[Path] = None) -> Path:
    base = appdata or Path(os.environ["APPDATA"])
    return base / "Piper" / "browser-auth-token"


def _validate_token(token: str) -> str:
    token = token.strip()
    if len(token) < _MIN_TOKEN_LENGTH or any(ch.isspace() for ch in token):
        raise ValueError("invalid browser authentication token")
    return token


def load_or_create_browser_token(path: Optional[Path] = None) -> str:
    path = path or browser_token_path()
    if path.exists():
        return _validate_token(path.read_text(encoding="utf-8"))

    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(token + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        temp_path = Path(handle.name)

    try:
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    return token
