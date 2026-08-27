from pathlib import Path

from piper.windows_tray.logging_setup import log_path


def test_log_path_uses_local_appdata(tmp_path: Path) -> None:
    assert log_path(tmp_path) == tmp_path / "Piper" / "piper-tray.log"
