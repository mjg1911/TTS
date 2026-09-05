import logging
import os
from importlib import metadata
from logging import Logger, getLogger
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional
import traceback


def log_path(local_appdata: Optional[Path] = None) -> Path:
    base = local_appdata or Path(os.environ["LOCALAPPDATA"])
    return base / "Piper" / "piper-tray.log"


def app_version() -> str:
    try:
        return metadata.version("piper-tts")
    except metadata.PackageNotFoundError:
        return "dev"


class _AppVersionFilter(logging.Filter):
    def __init__(self, version: str) -> None:
        super().__init__()
        self._version = version

    def filter(self, record: logging.LogRecord) -> bool:
        record.app_version = self._version
        return True


def configure_logging(
    level: str,
    path: Optional[Path] = None,
    console: bool = False,
) -> Logger:
    path = path or log_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    logger = getLogger("piper.windows_tray")
    logger.setLevel(getattr(logging, level))
    for existing_handler in logger.handlers:
        existing_handler.close()
    logger.handlers.clear()

    version_filter = _AppVersionFilter(app_version())
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s "
        "version=%(app_version)s %(message)s"
    )

    file_handler = RotatingFileHandler(
        path, maxBytes=1_048_576, backupCount=3, encoding="utf-8"
    )
    file_handler.addFilter(version_filter)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if console:
        console_handler = logging.StreamHandler()
        console_handler.addFilter(version_filter)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    logger.propagate = False
    return logger


def log_capture_result(
    logger: Logger,
    outcome: str,
    text_length: int,
) -> None:
    logger.info(
        "capture outcome=%s length=%d",
        outcome,
        text_length,
    )


def log_synthesis_result(
    logger: Logger,
    generation: int,
    elapsed_ms: int,
    outcome: str,
) -> None:
    logger.info(
        "synthesis generation=%d elapsed_ms=%d outcome=%s",
        generation,
        elapsed_ms,
        outcome,
    )


def log_codex_result(
    logger: Logger,
    *,
    conversation_id: str,
    turn_id: str,
    character_count: int,
    outcome: str,
) -> None:
    logger.info(
        "codex_response conversation_id=%s turn_id=%s character_count=%d outcome=%s",
        conversation_id,
        turn_id,
        character_count,
        outcome,
    )


def log_codex_status(logger: Logger, status: str) -> None:
    logger.info("codex_monitor status=%s", status)


def log_browser_status(
    logger: Logger,
    *,
    status: str,
    queue_size: int,
    outcome: Optional[str] = None,
) -> None:
    message = "browser_tts status=%s queue_size=%d"
    args = [status, queue_size]
    if outcome is not None:
        message += " outcome=%s"
        args.append(outcome)
    logger.info(message, *args)


def log_exception_safe(
    logger: Logger,
    event: str,
    error: BaseException,
    *,
    generation: Optional[int] = None,
    phase: Optional[str] = None,
    stage: Optional[str] = None,
) -> None:
    fields = []
    if generation is not None:
        fields.append(f"generation={generation}")
    if phase is not None:
        fields.append(f"phase={phase}")
    if stage is not None:
        fields.append(f"stage={stage}")

    frames = traceback.extract_tb(error.__traceback__)
    traceback_text = ">".join(
        f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}"
        for frame in frames
    )
    fields.append(f"exception_type={type(error).__name__}")
    fields.append(f"traceback={traceback_text or 'unavailable'}")
    logger.error("%s %s", event, " ".join(fields))
