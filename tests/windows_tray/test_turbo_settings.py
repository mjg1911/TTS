"""Turbo replaces Multilingual without losing saved user preferences."""

from dataclasses import asdict
import json

from piper.windows_tray.settings import TraySettings, load_settings, save_settings


def test_multilingual_selection_migrates_to_turbo(tmp_path):
    path = tmp_path / "settings.json"
    payload = asdict(TraySettings(pitch_percent=12, chatterbox_device="cuda"))
    payload.update(
        engine="Chatterbox Multilingual V3 (500M)",
        multilingual_language="nl",
        multilingual_exaggeration=1.25,
        multilingual_cfg_weight=0.8,
    )
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = load_settings(path)
    assert result.source == "loaded"
    assert result.settings.engine == "Chatterbox Turbo (350M)"
    assert result.settings.pitch_percent == 12
    assert result.settings.chatterbox_device == "cuda"
    assert "Turbo" in result.migration_notice
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["engine"] == "Chatterbox Turbo (350M)"
    assert not any(key.startswith("multilingual_") for key in persisted)


def test_turbo_round_trip_has_no_multilingual_options(tmp_path):
    path = tmp_path / "settings.json"
    settings = TraySettings(engine="Chatterbox Turbo (350M)")
    save_settings(settings, path)
    assert load_settings(path).settings == settings
    assert not any(key.startswith("multilingual_") for key in asdict(settings))
