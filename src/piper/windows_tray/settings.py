from dataclasses import asdict, dataclass
import json
import math
import numbers
import os
from pathlib import Path
import tempfile
from typing import Literal, Optional

from piper.turbo_options import ENGINE as TURBO_ENGINE
from piper.turbo_options import validate_delivery_mode

from . import (
    DEFAULT_HOTKEY,
    DEFAULT_PAUSE_RESUME_HOTKEY,
    DEFAULT_STOP_TTS_HOTKEY,
    DEFAULT_VOICE,
    SETTINGS_SCHEMA_VERSION,
)

DEFAULT_PITCH_PERCENT: float = 26.0
MIN_PITCH_PERCENT: float = -50.0
MAX_PITCH_PERCENT: float = 100.0
DEFAULT_SPEED_PERCENT: float = 0.0
MIN_SPEED_PERCENT: float = -50.0
MAX_SPEED_PERCENT: float = 100.0
DEFAULT_SENTENCE_PAUSE_MS: int = 180
MIN_SENTENCE_PAUSE_MS: int = 0
MAX_SENTENCE_PAUSE_MS: int = 2000
DEFAULT_PIPER_SENTENCE_STREAMING_ENABLED: bool = True


def validate_piper_sentence_streaming_enabled(value: object) -> bool:
    if type(value) is not bool:
        raise ValueError("piper_sentence_streaming_enabled must be a boolean")
    return value


def validate_chatterbox_custom_voice_enabled(value: object) -> bool:
    if type(value) is not bool:
        raise ValueError("chatterbox_custom_voice_enabled must be a boolean")
    return value


def validate_chatterbox_reference_clip(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("chatterbox_reference_clip must be a string")
    if value and not value.strip():
        raise ValueError("chatterbox_reference_clip must be empty or a path")
    return value


def validate_pitch_percent(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError("pitch_percent must be a finite number")
    pitch_percent = float(value)
    if not math.isfinite(pitch_percent):
        raise ValueError("pitch_percent must be a finite number")
    if not MIN_PITCH_PERCENT <= pitch_percent <= MAX_PITCH_PERCENT:
        raise ValueError("pitch_percent is out of range")
    return pitch_percent


def validate_speed_percent(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError("speed_percent must be a finite number")
    speed_percent = float(value)
    if not math.isfinite(speed_percent):
        raise ValueError("speed_percent must be a finite number")
    if not MIN_SPEED_PERCENT <= speed_percent <= MAX_SPEED_PERCENT:
        raise ValueError("speed_percent is out of range")
    return speed_percent


def validate_sentence_pause_ms(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, numbers.Integral):
        raise ValueError("sentence_pause_ms must be a whole number")
    sentence_pause_ms = int(value)
    if not MIN_SENTENCE_PAUSE_MS <= sentence_pause_ms <= MAX_SENTENCE_PAUSE_MS:
        raise ValueError("sentence_pause_ms is out of range")
    return sentence_pause_ms


@dataclass(frozen=True, init=False)
class TraySettings:
    chatterbox_device: Literal["cpu", "cuda"] = "cpu"
    chatterbox_custom_voice_enabled: bool = False
    chatterbox_reference_clip: str = ""
    turbo_delivery_mode: str = ""
    schema_version: int = SETTINGS_SCHEMA_VERSION
    engine: Literal["Piper", "Chatterbox Nano", "Chatterbox Turbo (350M)"] = "Piper"
    piper_voice: str = DEFAULT_VOICE
    hotkey: str = DEFAULT_HOTKEY
    stop_tts_hotkey: str = DEFAULT_STOP_TTS_HOTKEY
    pause_resume_hotkey: str = DEFAULT_PAUSE_RESUME_HOTKEY
    log_level: str = "INFO"
    error_sounds: bool = False
    codex_enabled: bool = False
    browser_chatgpt_enabled: bool = False
    pitch_percent: float = DEFAULT_PITCH_PERCENT
    speed_percent: float = DEFAULT_SPEED_PERCENT
    sentence_pause_ms: int = DEFAULT_SENTENCE_PAUSE_MS
    piper_sentence_streaming_enabled: bool = DEFAULT_PIPER_SENTENCE_STREAMING_ENABLED

    def __init__(
        self,
        schema_version: int = SETTINGS_SCHEMA_VERSION,
        engine: Literal[
            "Piper", "Chatterbox Nano", "Chatterbox Turbo (350M)"
        ] = "Piper",
        piper_voice: str = DEFAULT_VOICE,
        hotkey: str = DEFAULT_HOTKEY,
        log_level: str = "INFO",
        error_sounds: bool = False,
        codex_enabled: bool = False,
        browser_chatgpt_enabled: bool = False,
        pitch_percent: float = DEFAULT_PITCH_PERCENT,
        speed_percent: float = DEFAULT_SPEED_PERCENT,
        sentence_pause_ms: int = DEFAULT_SENTENCE_PAUSE_MS,
        piper_sentence_streaming_enabled: bool = (
            DEFAULT_PIPER_SENTENCE_STREAMING_ENABLED
        ),
        *,
        stop_tts_hotkey: str = DEFAULT_STOP_TTS_HOTKEY,
        pause_resume_hotkey: str = DEFAULT_PAUSE_RESUME_HOTKEY,
        chatterbox_device: Literal["cpu", "cuda"] = "cpu",
        chatterbox_custom_voice_enabled: bool = False,
        chatterbox_reference_clip: str = "",
        turbo_delivery_mode: str = "",
        voice: Optional[str] = None,
    ) -> None:
        if voice is not None and piper_voice == DEFAULT_VOICE:
            piper_voice = voice
        for name, value in locals().items():
            if name not in {"self", "voice"}:
                object.__setattr__(self, name, value)

    @property
    def voice(self) -> str:
        """Compatibility alias for callers that only support Piper."""
        return self.piper_voice


@dataclass(frozen=True)
class SettingsLoadResult:
    settings: TraySettings
    source: Literal["loaded", "missing", "corrupt"]
    migration_notice: Optional[str] = None


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

    engine = data.get("engine", "Piper")
    chatterbox_device = data.get("chatterbox_device", "cpu")
    chatterbox_custom_voice_enabled = validate_chatterbox_custom_voice_enabled(
        data.get("chatterbox_custom_voice_enabled", False)
    )
    chatterbox_reference_clip = validate_chatterbox_reference_clip(
        data.get("chatterbox_reference_clip", "")
    )
    turbo_delivery_mode = validate_delivery_mode(
        data.get("turbo_delivery_mode", "")
    )
    if chatterbox_device not in ("cpu", "cuda"):
        raise ValueError("invalid Chatterbox device")
    piper_voice = data.get("piper_voice")
    hotkey = data.get("hotkey")
    log_level = data.get("log_level", "INFO")
    error_sounds = data.get("error_sounds", False)
    codex_enabled = data.get("codex_enabled", False)
    browser_chatgpt_enabled = data.get("browser_chatgpt_enabled", False)
    pitch_percent = validate_pitch_percent(
        data.get("pitch_percent", DEFAULT_PITCH_PERCENT)
    )
    speed_percent = validate_speed_percent(
        data.get("speed_percent", DEFAULT_SPEED_PERCENT)
    )
    sentence_pause_ms = validate_sentence_pause_ms(
        data.get("sentence_pause_ms", DEFAULT_SENTENCE_PAUSE_MS)
    )
    piper_sentence_streaming_enabled = validate_piper_sentence_streaming_enabled(
        data.get(
            "piper_sentence_streaming_enabled",
            DEFAULT_PIPER_SENTENCE_STREAMING_ENABLED,
        )
    )
    if not isinstance(engine, str) or engine not in {
        "Piper",
        "Chatterbox Nano",
        TURBO_ENGINE,
    }:
        raise ValueError("invalid engine")
    if not isinstance(piper_voice, str) or not piper_voice.strip():
        raise ValueError("piper_voice must be a non-empty string")
    if not isinstance(hotkey, str) or not hotkey.strip():
        raise ValueError("hotkey must be a non-empty string")
    stop_tts_hotkey = data.get("stop_tts_hotkey", DEFAULT_STOP_TTS_HOTKEY)
    pause_resume_hotkey = data.get(
        "pause_resume_hotkey", DEFAULT_PAUSE_RESUME_HOTKEY
    )
    if not isinstance(stop_tts_hotkey, str) or not stop_tts_hotkey.strip():
        raise ValueError("stop_tts_hotkey must be a non-empty string")
    if not isinstance(pause_resume_hotkey, str) or not pause_resume_hotkey.strip():
        raise ValueError("pause_resume_hotkey must be a non-empty string")
    if not isinstance(log_level, str) or log_level not in {
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
    }:
        raise ValueError("invalid log level")
    if type(error_sounds) is not bool:
        raise ValueError("error_sounds must be a boolean")
    if type(codex_enabled) is not bool:
        raise ValueError("codex_enabled must be a boolean")
    if type(browser_chatgpt_enabled) is not bool:
        raise ValueError("browser_chatgpt_enabled must be a boolean")
    return TraySettings(
        chatterbox_device=chatterbox_device,
        chatterbox_custom_voice_enabled=chatterbox_custom_voice_enabled,
        chatterbox_reference_clip=chatterbox_reference_clip,
        turbo_delivery_mode=turbo_delivery_mode,
        engine=engine,
        piper_voice=piper_voice.strip(),
        hotkey=hotkey.strip(),
        stop_tts_hotkey=stop_tts_hotkey.strip(),
        pause_resume_hotkey=pause_resume_hotkey.strip(),
        log_level=log_level,
        error_sounds=error_sounds,
        codex_enabled=codex_enabled,
        browser_chatgpt_enabled=browser_chatgpt_enabled,
        pitch_percent=pitch_percent,
        speed_percent=speed_percent,
        sentence_pause_ms=sentence_pause_ms,
        piper_sentence_streaming_enabled=piper_sentence_streaming_enabled,
    )


def _corrupt_path(path: Path) -> Path:
    candidate = path.with_name(path.name + ".corrupt")
    index = 1
    while candidate.exists():
        candidate = path.with_name(path.name + f".corrupt.{index}")
        index += 1
    return candidate


def _migrate(data: object) -> tuple[object, bool, Optional[str]]:
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int:
        return data, False, None
    schema_version = data.get("schema_version")
    if schema_version not in (1, 2, SETTINGS_SCHEMA_VERSION):
        return data, False, None

    migrated = dict(data)
    changed = False
    migration_notice = None

    if schema_version == 1:
        legacy_voice = migrated.pop("voice", DEFAULT_VOICE)
        migrated["schema_version"] = 2
        migrated["piper_voice"] = legacy_voice
        migrated.setdefault("engine", "Piper")
        changed = True

    if schema_version in (1, 2):
        migrated.setdefault("stop_tts_hotkey", DEFAULT_STOP_TTS_HOTKEY)
        migrated.setdefault("pause_resume_hotkey", DEFAULT_PAUSE_RESUME_HOTKEY)
        migrated["schema_version"] = SETTINGS_SCHEMA_VERSION
        changed = True

    if migrated.get("engine") == "Kokoro":
        migrated["engine"] = "Piper"
        migration_notice = "Kokoro is no longer available. Piper has been selected."
        changed = True

    if "kokoro_voice" in migrated:
        del migrated["kokoro_voice"]
        changed = True

    if migrated.get("engine") == "Chatterbox Multilingual V3 (500M)":
        migrated["engine"] = "Chatterbox Turbo (350M)"
        migration_notice = (
            "Chatterbox Multilingual has been replaced by "
            "Chatterbox Turbo (English only)."
        )
        changed = True

    for field in (
        "multilingual_language",
        "multilingual_exaggeration",
        "multilingual_cfg_weight",
    ):
        if field in migrated:
            del migrated[field]
            changed = True

    return migrated, changed, migration_notice


def load_settings(path: Optional[Path] = None) -> SettingsLoadResult:
    path = path or settings_path()
    try:
        if not path.exists():
            return SettingsLoadResult(TraySettings(), "missing")
        data, migrated, migration_notice = _migrate(
            json.loads(path.read_text(encoding="utf-8"))
        )
        settings = _validated(data)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        try:
            path.replace(_corrupt_path(path))
        except OSError:
            pass
        return SettingsLoadResult(TraySettings(), "corrupt")

    if migrated:
        try:
            save_settings(settings, path)
        except OSError:
            pass
    return SettingsLoadResult(settings, "loaded", migration_notice)


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
    try:
        os.replace(temp_path, path)
    except OSError:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise
