import json
from pathlib import Path

import pytest

from piper.windows_tray.settings import (
    TraySettings,
    load_settings,
    save_settings,
)


def test_missing_settings_use_safe_defaults(tmp_path: Path) -> None:
    result = load_settings(tmp_path / "settings.json")
    assert result.settings == TraySettings()
    assert result.source == "missing"


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
