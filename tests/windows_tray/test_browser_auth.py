from pathlib import Path

import pytest

from piper.windows_tray.browser_auth import (
    browser_token_path,
    load_or_create_browser_token,
)


def test_browser_token_path_uses_piper_appdata(tmp_path: Path) -> None:
    assert browser_token_path(tmp_path) == tmp_path / "Piper" / "browser-auth-token"


def test_load_or_create_browser_token_is_stable(tmp_path: Path) -> None:
    path = tmp_path / "browser-auth-token"
    first = load_or_create_browser_token(path)
    second = load_or_create_browser_token(path)
    assert first == second
    assert len(first) >= 40
    assert path.read_text(encoding="utf-8") == first + "\n"


def test_invalid_saved_browser_token_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "browser-auth-token"
    path.write_text("short\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid browser authentication token"):
        load_or_create_browser_token(path)
