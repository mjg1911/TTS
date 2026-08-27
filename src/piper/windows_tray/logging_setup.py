import logging
import os
from logging import Logger, getLogger
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


def log_path(local_appdata: Optional[Path] = None) -> Path:
    base = local_appdata or Path(os.environ["LOCALAPPDATA"])
    return base / "Piper" / "piper-tray.log"


def configure_logging(level: str, path: Optional[Path] = None) -> Logger:
    path = path or log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        path, maxBytes=1_048_576, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger = getLogger("piper.windows_tray")
    logger.setLevel(getattr(logging, level))
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.propagate = False
    return logger
