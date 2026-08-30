from dataclasses import asdict, dataclass
import json
import math
import numbers
import os
from pathlib import Path
import tempfile
from typing import Literal, Optional

from . import DEFAULT_HOTKEY, DEFAULT_VOICE, SETTINGS_SCHEMA_VERSION

DEFAULT_PITCH_PERCENT: float = 26.0
MIN_PITCH_PERCENT: float = -50.0
MAX_PITCH_PERCENT: float = 100.0


def validate_pitch_percent(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError("pitch_percent must be a finite number")
    pitch_percent = float(value)
    if not math.isfinite(pitch_percent):
        raise ValueError("pitch_percent must be a finite number")
    if not MIN_PITCH_PERCENT <= pitch_percent <= MAX_PITCH_PERCENT:
        raise ValueError("pitch_percent is out of range")
    return pitch_percent


@dataclass(frozen=True)
class TraySettings:
    schema_version: int = SETTINGS_SCHEMA_VERSION
    voice: str = DEFAULT_VOICE
    hotkey: str = DEFAULT_HOTKEY
    log_level: str = "INFO"
    error_sounds: bool = False
    pitch_percent: float = DEFAULT_PITCH_PERCENT


@dataclass(frozen=True)
class SettingsLoadResult:
    settings: TraySettings
    source: Literal["loaded", "missing", "corrupt"]


def settings_path(appdata: Optional[Path] = None) -> Path:
    base = appdata or Path(os.environ["APPDATA"])
    return base / "Piper" / "settings.json"


def _validated(data: object) -> TraySettings:
    if not isinstance(data, dict):
        raise ValueError("settings root must be an object")
    if (
        type(data.get("schema_version")) is not int
        or data.get("schema_version") != SETTINGS_SCHEMA_VERSION
    ):
        raise ValueError("unsupported settings schema")

    voice = data.get("voice")
    hotkey = data.get("hotkey")
    log_level = data.get("log_level", "INFO")
    error_sounds = data.get("error_sounds", False)
    pitch_percent = validate_pitch_percent(
        data.get("pitch_percent", DEFAULT_PITCH_PERCENT)
    )
    if not isinstance(voice, str) or not voice.strip():
        raise ValueError("voice must be a non-empty string")
    if not isinstance(hotkey, str) or not hotkey.strip():
        raise ValueError("hotkey must be a non-empty string")
    if not isinstance(log_level, str) or log_level not in {
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
    }:
        raise ValueError("invalid log level")
    if type(error_sounds) is not bool:
        raise ValueError("error_sounds must be a boolean")
    return TraySettings(
        voice=voice.strip(),
        hotkey=hotkey.strip(),
        log_level=log_level,
        error_sounds=error_sounds,
        pitch_percent=pitch_percent,
    )


def _corrupt_path(path: Path) -> Path:
    candidate = path.with_name(path.name + ".corrupt")
    index = 1
    while candidate.exists():
        candidate = path.with_name(path.name + f".corrupt.{index}")
        index += 1
    return candidate


def load_settings(path: Optional[Path] = None) -> SettingsLoadResult:
    path = path or settings_path()
    try:
        if not path.exists():
            return SettingsLoadResult(TraySettings(), "missing")
        return SettingsLoadResult(
            _validated(json.loads(path.read_text(encoding="utf-8"))), "loaded"
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        try:
            path.replace(_corrupt_path(path))
        except OSError:
            pass
        return SettingsLoadResult(TraySettings(), "corrupt")


def save_settings(settings: TraySettings, path: Optional[Path] = None) -> None:
    settings = _validated(asdict(settings))

    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(asdict(settings), indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        temp_path = Path(handle.name)
    os.replace(temp_path, path)
