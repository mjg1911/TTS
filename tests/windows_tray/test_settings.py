import json
import math
from pathlib import Path

import pytest

from piper.windows_tray.settings import (
    DEFAULT_SPEED_PERCENT,
    DEFAULT_PITCH_PERCENT,
    MAX_SPEED_PERCENT,
    MAX_PITCH_PERCENT,
    MIN_SPEED_PERCENT,
    MIN_PITCH_PERCENT,
    TraySettings,
    load_settings,
    save_settings,
    validate_speed_percent,
    validate_pitch_percent,
)


def _write_v1_settings(path: Path, **overrides) -> None:
    settings = {
        "schema_version": 1,
        "voice": "en_GB-alba-medium",
        "hotkey": "alt+backtick",
        "log_level": "INFO",
    }
    settings.update(overrides)
    path.write_text(json.dumps(settings), encoding="utf-8")


def test_missing_settings_use_safe_defaults(tmp_path: Path) -> None:
    result = load_settings(tmp_path / "settings.json")
    assert result.settings == TraySettings()
    assert result.source == "missing"


def test_old_settings_default_codex_enabled_to_false(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    _write_v1_settings(path)
    assert load_settings(path).settings.codex_enabled is False


def test_old_settings_default_browser_chatgpt_enabled_to_false(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    _write_v1_settings(path)
    result = load_settings(path)
    assert result.settings.browser_chatgpt_enabled is False
    assert result.source == "loaded"


def test_browser_chatgpt_enabled_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    save_settings(TraySettings(browser_chatgpt_enabled=True), path)
    assert load_settings(path).settings.browser_chatgpt_enabled is True


@pytest.mark.parametrize("value", [1, 0, "true", "false", [], {}])
def test_invalid_browser_chatgpt_enabled_is_corrupt(tmp_path: Path, value) -> None:
    path = tmp_path / "settings.json"
    _write_v1_settings(path, browser_chatgpt_enabled=value)
    result = load_settings(path)
    assert result.settings == TraySettings()
    assert result.source == "corrupt"


def test_codex_enabled_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    save_settings(TraySettings(codex_enabled=True), path)
    assert load_settings(path).settings.codex_enabled is True


@pytest.mark.parametrize("value", [1, 0, "true", "false", [], {}])
def test_invalid_codex_enabled_is_treated_as_corrupt(tmp_path: Path, value) -> None:
    path = tmp_path / "settings.json"
    _write_v1_settings(path, codex_enabled=value)
    result = load_settings(path)
    assert result.settings == TraySettings()
    assert result.source == "corrupt"


@pytest.mark.parametrize("value", [-50, -12.5, 0, 26, 100])
def test_validate_pitch_percent_accepts_finite_values_inclusive(value) -> None:
    assert validate_pitch_percent(value) == float(value)


@pytest.mark.parametrize(
    "value", [-50.0001, 100.0001, "26", None, True, math.nan, math.inf, -math.inf]
)
def test_validate_pitch_percent_rejects_invalid_values(value) -> None:
    with pytest.raises(ValueError):
        validate_pitch_percent(value)


def test_pitch_constants_define_schema_range() -> None:
    assert DEFAULT_PITCH_PERCENT == 26.0
    assert MIN_PITCH_PERCENT == -50.0
    assert MAX_PITCH_PERCENT == 100.0


def test_schema_one_settings_missing_pitch_use_default(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    _write_v1_settings(path)

    result = load_settings(path)

    assert result.settings.pitch_percent == DEFAULT_PITCH_PERCENT
    assert result.source == "loaded"


def test_pitch_settings_round_trip_for_schema_one(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"

    save_settings(TraySettings(pitch_percent=-12.5), path)

    result = load_settings(path)

    assert result.settings.pitch_percent == -12.5
    assert result.source == "loaded"


def test_invalid_pitch_save_preserves_existing_file(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "settings.json"
    original = '{"schema_version": 1, "pitch_percent": 26.0}\n'
    path.write_text(original, encoding="utf-8")

    def unexpected_temp_file(*args, **kwargs):
        raise AssertionError("temporary file must not be created")

    monkeypatch.setattr(
        "piper.windows_tray.settings.tempfile.NamedTemporaryFile", unexpected_temp_file
    )

    with pytest.raises(ValueError):
        save_settings(TraySettings(pitch_percent=100.0001), path)

    assert path.read_text(encoding="utf-8") == original


def test_unreadable_settings_use_safe_defaults(monkeypatch, tmp_path: Path) -> None:
    from piper.windows_tray import settings

    monkeypatch.setattr(
        settings.Path,
        "exists",
        lambda _path: (_ for _ in ()).throw(PermissionError("denied")),
    )

    result = settings.load_settings(tmp_path / "settings.json")

    assert result.settings == TraySettings()
    assert result.source == "corrupt"


def test_malformed_settings_are_preserved_and_replaced_in_memory(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{broken", encoding="utf-8")

    result = load_settings(path)

    assert result.settings == TraySettings()
    assert result.source == "corrupt"
    assert not path.exists()
    assert (tmp_path / "settings.json.corrupt").read_text(encoding="utf-8") == "{broken"


def test_save_settings_uses_replace_and_writes_schema_version(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "settings.json"
    replacements = []

    def fake_replace(source, target) -> None:
        replacements.append((Path(source), Path(target)))
        Path(target).write_bytes(Path(source).read_bytes())
        Path(source).unlink()

    monkeypatch.setattr("piper.windows_tray.settings.os.replace", fake_replace)
    save_settings(TraySettings(), path)

    assert replacements and replacements[0][1] == path
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 1


def test_old_settings_default_error_sounds_to_false(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    _write_v1_settings(path)

    result = load_settings(path)

    assert result.settings.error_sounds is False
    assert result.source == "loaded"


def test_error_sounds_round_trip_persistence(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"

    save_settings(TraySettings(error_sounds=True), path)

    result = load_settings(path)

    assert result.settings.error_sounds is True
    assert result.source == "loaded"


@pytest.mark.parametrize("error_sounds", [1, 0, "true", "false", [], {}])
def test_invalid_error_sounds_are_preserved_as_corrupt(
    tmp_path: Path, error_sounds
) -> None:
    path = tmp_path / "settings.json"
    _write_v1_settings(path, error_sounds=error_sounds)

    result = load_settings(path)

    assert result.settings == TraySettings()
    assert result.source == "corrupt"
    assert not path.exists()
    assert list(tmp_path.glob("settings.json.corrupt*"))


def test_non_integer_schema_version_is_preserved_as_corrupt(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "voice": "en_GB-alba-medium",
                "hotkey": "alt+backtick",
            }
        ),
        encoding="utf-8",
    )

    result = load_settings(path)

    assert result.settings == TraySettings()
    assert result.source == "corrupt"
    assert not path.exists()
    assert list(tmp_path.glob("settings.json.corrupt*"))


def test_invalid_log_level_is_preserved_as_corrupt(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "voice": "en_GB-alba-medium",
                "hotkey": "alt+backtick",
                "log_level": "TRACE",
            }
        ),
        encoding="utf-8",
    )

    result = load_settings(path)

    assert result.settings == TraySettings()
    assert result.source == "corrupt"
    assert not path.exists()
    assert list(tmp_path.glob("settings.json.corrupt*"))


def test_boolean_schema_version_is_preserved_as_corrupt(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": True,
                "voice": "en_GB-alba-medium",
                "hotkey": "alt+backtick",
            }
        ),
        encoding="utf-8",
    )

    result = load_settings(path)

    assert result.settings == TraySettings()
    assert result.source == "corrupt"
    assert not path.exists()
    assert list(tmp_path.glob("settings.json.corrupt*"))


@pytest.mark.parametrize("log_level", [["INFO"], {"level": "INFO"}])
def test_unhashable_log_level_is_preserved_as_corrupt(
    tmp_path: Path, log_level
) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "voice": "en_GB-alba-medium",
                "hotkey": "alt+backtick",
                "log_level": log_level,
            }
        ),
        encoding="utf-8",
    )

    result = load_settings(path)

    assert result.settings == TraySettings()
    assert result.source == "corrupt"
    assert not path.exists()
    assert list(tmp_path.glob("settings.json.corrupt*"))


def test_save_settings_rejects_non_v1_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"

    with pytest.raises(ValueError, match="unsupported settings schema"):
        save_settings(TraySettings(schema_version=2), path)

    assert not path.exists()


@pytest.mark.parametrize("value", [-50, -12.5, 0, 50, 100])
def test_validate_speed_percent_accepts_finite_values_inclusive(value) -> None:
    assert validate_speed_percent(value) == float(value)


@pytest.mark.parametrize(
    "value", [-50.0001, 100.0001, "50", None, True, math.nan, math.inf, -math.inf]
)
def test_validate_speed_percent_rejects_invalid_values(value) -> None:
    with pytest.raises(ValueError):
        validate_speed_percent(value)


def test_speed_constants_define_schema_range() -> None:
    assert DEFAULT_SPEED_PERCENT == 0.0
    assert MIN_SPEED_PERCENT == -50.0
    assert MAX_SPEED_PERCENT == 100.0


def test_schema_one_settings_missing_speed_use_default(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    _write_v1_settings(path)

    result = load_settings(path)

    assert result.settings.speed_percent == DEFAULT_SPEED_PERCENT
    assert result.source == "loaded"


def test_speed_settings_round_trip_for_schema_one(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"

    save_settings(TraySettings(speed_percent=-12.5), path)

    result = load_settings(path)

    assert result.settings.speed_percent == -12.5
    assert result.source == "loaded"


def test_invalid_speed_settings_are_preserved_as_corrupt(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    _write_v1_settings(path, speed_percent=100.0001)

    result = load_settings(path)

    assert result.settings == TraySettings()
    assert result.source == "corrupt"
    assert not path.exists()
    assert list(tmp_path.glob("settings.json.corrupt*"))


def test_invalid_speed_save_does_not_create_temp_file(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "settings.json"

    def unexpected_temp_file(*args, **kwargs):
        raise AssertionError("temporary file must not be created")

    monkeypatch.setattr(
        "piper.windows_tray.settings.tempfile.NamedTemporaryFile", unexpected_temp_file
    )

    with pytest.raises(ValueError):
        save_settings(TraySettings(speed_percent=100.0001), path)

    assert not path.exists()
