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


def test_every_configured_log_line_contains_app_version(tmp_path: Path) -> None:
    path = tmp_path / "piper-tray.log"
    logger = configure_logging("INFO", path=path)

    logger.info("hello")
    for handler in logger.handlers:
        handler.flush()

    text = path.read_text(encoding="utf-8")
    assert "version=" in text
    assert "hello" in text


def test_debug_logging_can_mirror_to_console(tmp_path, capsys) -> None:
    logger = configure_logging(
        "DEBUG",
        path=tmp_path / "piper-tray.log",
        console=True,
    )
    logger.debug("debug-visible")

    captured = capsys.readouterr()
    assert "debug-visible" in captured.err
    assert "debug-visible" in (tmp_path / "piper-tray.log").read_text(
        encoding="utf-8"
    )


def test_normal_logging_does_not_add_console_handler(tmp_path, capsys) -> None:
    logger = configure_logging(
        "INFO",
        path=tmp_path / "piper-tray.log",
        console=False,
    )
    logger.info("file-only")

    assert "file-only" not in capsys.readouterr().err
    assert "file-only" in (tmp_path / "piper-tray.log").read_text(
        encoding="utf-8"
    )
