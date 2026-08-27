from pathlib import Path

from piper.windows_tray.logging_setup import configure_logging, log_path


def test_log_path_uses_local_appdata(tmp_path: Path) -> None:
    assert log_path(tmp_path) == tmp_path / "Piper" / "piper-tray.log"


def test_reconfiguration_closes_existing_handlers(tmp_path: Path) -> None:
    logger = configure_logging("INFO", tmp_path / "piper-tray.log")
    old_handler = logger.handlers[0]

    try:
        configure_logging("INFO", tmp_path / "piper-tray.log")
        assert old_handler.stream is None
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers.clear()
