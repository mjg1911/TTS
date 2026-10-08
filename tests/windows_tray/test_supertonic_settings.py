"""Settings persistence and UI for the Supertonic engine."""

import json
from pathlib import Path

import pytest

from piper.windows_tray.settings import TraySettings, load_settings, save_settings


def test_older_settings_without_device_continue_using_gpu(tmp_path):
    path = tmp_path / 'settings.json'
    save_settings(TraySettings(engine='Supertonic 3'), path)
    payload = json.loads(path.read_text(encoding='utf-8'))
    del payload['supertonic_device']
    path.write_text(json.dumps(payload), encoding='utf-8')
    loaded = load_settings(path)
    assert loaded.source == 'loaded'
    assert loaded.settings.supertonic_device == 'cuda'


def test_supertonic_voice_and_language_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"

    defaults = TraySettings()
    assert defaults.supertonic_voice == "M1"
    assert defaults.supertonic_language == "en"
    assert defaults.supertonic_device == "cuda"

    save_settings(
        TraySettings(
            engine="Supertonic 3",
            supertonic_voice="F3",
            supertonic_language="fr",
            supertonic_device="cpu",
        ),
        path,
    )

    result = load_settings(path)

    assert result.source == "loaded"
    assert result.settings.engine == "Supertonic 3"
    assert result.settings.supertonic_voice == "F3"
    assert result.settings.supertonic_language == "fr"
    assert result.settings.supertonic_device == "cpu"


@pytest.mark.parametrize(
    ("field", "value"),
    (("supertonic_voice", "M6"), ("supertonic_language", "xx"), ("supertonic_device", "auto")),
)
def test_invalid_supertonic_settings_are_preserved_as_corrupt(
    tmp_path: Path, field: str, value: str
) -> None:
    path = tmp_path / "settings.json"
    payload = {
        "schema_version": 3,
        "engine": "Supertonic 3",
        "piper_voice": "en_GB-alba-medium",
        "hotkey": "alt+backtick",
        "supertonic_voice": "M1",
        "supertonic_language": "en",
    }
    payload[field] = value
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = load_settings(path)

    assert result.source == "corrupt"
    assert not path.exists()
    assert path.with_name("settings.json.corrupt").exists()


def test_supertonic_settings_controls_follow_snapshot_and_hide_chatterbox_options(
    monkeypatch,
) -> None:
    from tests.windows_tray.test_settings_window import install_fake_tk, make_snapshot
    from piper.supertonic_options import ENGINE, LANGUAGES, VOICES
    from piper.windows_tray.controller import SettingsApplyResult
    import piper.windows_tray.settings_window as settings_window

    install_fake_tk(monkeypatch, [])
    monkeypatch.setattr(settings_window, "configure_studio_theme", lambda _window: None)
    monkeypatch.setattr(settings_window, "choose_voice_model", lambda _parent: None)
    snapshot = make_snapshot(
        engine=ENGINE,
        supertonic_voice="F3",
        supertonic_language="fr",
        supertonic_device="cpu",
    )
    window = settings_window.SettingsWindow(
        parent=object(),
        snapshot=snapshot,
        on_apply=lambda *_args, **_options: SettingsApplyResult(True),
        on_close=lambda: None,
        on_speak_text=lambda _text: None,
    )

    assert ENGINE in window.engine_combo.kwargs["values"]
    assert window.supertonic_voice_var.get() == "F3"
    assert window.supertonic_language_var.get() == "French (fr)"
    assert window.supertonic_device_var.get() == "cpu"
    assert window.supertonic_voice_combo.kwargs["values"] == tuple(
        code for code, _label in VOICES
    )
    assert window.supertonic_language_combo.kwargs["values"] == tuple(
        f"{label} ({code})" for code, label in LANGUAGES
    )

    window._refresh_voice_controls()

    assert window.supertonic_voice_frame.hidden is False
    assert window.nano_voice_frame.hidden is True


def test_supertonic_settings_are_passed_to_controller_on_save(monkeypatch) -> None:
    from tests.windows_tray.test_settings_window import (
        drain_apply,
        install_fake_tk,
        make_snapshot,
    )
    from piper.supertonic_options import ENGINE
    from piper.windows_tray.controller import SettingsApplyResult
    import piper.windows_tray.settings_window as settings_window

    install_fake_tk(monkeypatch, [])
    monkeypatch.setattr(settings_window, "configure_studio_theme", lambda _window: None)
    monkeypatch.setattr(settings_window, "choose_voice_model", lambda _parent: None)
    received = []

    class ControllerCallback:
        def cancel_nano_settings(self):
            pass

        def apply(self, *_args, **options):
            received.append(options)
            return SettingsApplyResult(True)

    window = settings_window.SettingsWindow(
        parent=object(),
        snapshot=make_snapshot(
            engine=ENGINE,
            supertonic_voice="F3",
            supertonic_language="fr",
            supertonic_device="cpu",
        ),
        on_apply=ControllerCallback().apply,
        on_close=lambda: None,
        on_speak_text=lambda _text: None,
    )

    window._apply()
    drain_apply(window)

    assert received[0]["supertonic_voice"] == "F3"
    assert received[0]["supertonic_language"] == "fr"
    assert received[0]["supertonic_device"] == "cpu"
