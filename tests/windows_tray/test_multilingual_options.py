"""Settings and UI integration for Chatterbox Multilingual V3."""

from dataclasses import asdict
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from piper.multilingual_options import ENGINE
from piper.windows_tray.backend_manager import (
    BackendCandidate,
    BackendManager,
    BackendPreparationError,
)
from piper.windows_tray.controller import Controller, SettingsApplyResult
from piper.windows_tray.settings import TraySettings, load_settings, save_settings


def _controller(settings=None, save=None, prepare=None):
    preparations = []
    current_backend = object()

    def prepare_backend(engine, voice):
        preparation = controller.multilingual_preparation_options()
        preparations.append((engine, voice, preparation))
        if prepare is not None:
            return prepare(engine, voice)
        return BackendCandidate(engine, voice, object())

    manager = BackendManager(
        "Piper", "old", current_backend, lambda: None, prepare_backend
    )
    hotkeys = SimpleNamespace(
        prepare_rebind=lambda _: True,
        commit_rebind=lambda: True,
        rollback_rebind=lambda: True,
    )
    controller = Controller(
        settings=settings or TraySettings(piper_voice="old"),
        save_settings=save or (lambda _settings: None),
        hotkeys=hotkeys,
        backend_manager=manager,
    )
    controller._resolve_voice = lambda reference: Path(reference)
    return controller, manager, preparations


def test_multilingual_settings_default_and_round_trip(tmp_path):
    defaults = TraySettings()
    assert defaults.multilingual_language == "en"
    assert defaults.multilingual_exaggeration == 0.5
    assert defaults.multilingual_cfg_weight == 0.5

    settings = TraySettings(
        engine=ENGINE,
        multilingual_language="fr",
        multilingual_exaggeration=1.25,
        multilingual_cfg_weight=0.8,
    )
    path = tmp_path / "settings.json"
    save_settings(settings, path)

    assert load_settings(path).settings == settings
    assert json.loads(path.read_text(encoding="utf-8"))["engine"] == ENGINE


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("multilingual_language", "xx"),
        ("multilingual_exaggeration", 0.249),
        ("multilingual_exaggeration", 2.001),
        ("multilingual_exaggeration", True),
        ("multilingual_cfg_weight", -0.001),
        ("multilingual_cfg_weight", 1.001),
        ("multilingual_cfg_weight", float("nan")),
    ],
)
def test_invalid_multilingual_settings_are_treated_as_corrupt(
    tmp_path, field, value
):
    path = tmp_path / "settings.json"
    payload = asdict(TraySettings())
    payload[field] = value
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = load_settings(path)

    assert result.source == "corrupt"
    assert result.settings == TraySettings()
    assert list(tmp_path.glob("settings.json.corrupt*"))


def test_older_settings_receive_multilingual_defaults(tmp_path):
    payload = asdict(TraySettings())
    for field in (
        "multilingual_language",
        "multilingual_exaggeration",
        "multilingual_cfg_weight",
    ):
        payload.pop(field)
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = load_settings(path)

    assert result.source == "loaded"
    assert result.settings.multilingual_language == "en"
    assert result.settings.multilingual_exaggeration == 0.5
    assert result.settings.multilingual_cfg_weight == 0.5


def test_multilingual_apply_prepares_with_requested_options_and_snapshots_them():
    saved = []
    controller, _manager, preparations = _controller(save=saved.append)
    requested = {
        "language": "de",
        "exaggeration": 1.4,
        "cfg_weight": 0.75,
    }

    result = controller.apply_settings(
        ENGINE,
        "alt+backtick",
        "26",
        "0",
        None,
        multilingual_language=requested["language"],
        multilingual_exaggeration=requested["exaggeration"],
        multilingual_cfg_weight=requested["cfg_weight"],
    )

    assert result.applied is True
    assert preparations == [(ENGINE, "default", requested)]
    assert controller.state.settings.engine == ENGINE
    assert controller.multilingual_preparation_options() == requested
    assert result.snapshot.multilingual_language == "de"
    assert result.snapshot.multilingual_exaggeration == 1.4
    assert result.snapshot.multilingual_cfg_weight == 0.75
    assert saved[-1] == controller.state.settings


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("multilingual_language", "unknown"),
        ("multilingual_exaggeration", 2.1),
        ("multilingual_cfg_weight", -0.1),
    ],
)
def test_invalid_multilingual_apply_does_not_prepare_or_change_settings(field, value):
    controller, _manager, preparations = _controller()
    before = controller.state.settings

    result = controller.apply_settings(
        ENGINE,
        "alt+backtick",
        "26",
        "0",
        None,
        **{field: value},
    )

    assert result.applied is False
    assert field.removeprefix("multilingual_") in result.error_map()
    assert preparations == []
    assert controller.state.settings == before


def test_multilingual_preparation_failure_preserves_active_backend_and_settings():
    before = TraySettings(piper_voice="old")
    controller, manager, preparations = _controller(
        settings=before,
        prepare=lambda _engine, _voice: (_ for _ in ()).throw(
            BackendPreparationError("CUDA initialization failed")
        ),
    )
    active_backend = manager.current()

    result = controller.apply_settings(
        ENGINE,
        "alt+backtick",
        "26",
        "0",
        None,
        multilingual_language="fr",
    )

    assert result.applied is False
    assert controller.state.settings == before
    assert manager.current() is active_backend
    assert preparations == [(ENGINE, "default", {
        "language": "fr",
        "exaggeration": 0.5,
        "cfg_weight": 0.5,
    })]


def test_multilingual_save_failure_discards_candidate_and_keeps_saved_settings():
    before = TraySettings(piper_voice="old")
    discarded = []
    controller, manager, _preparations = _controller(
        settings=before,
        save=lambda _settings: (_ for _ in ()).throw(OSError("disk is full")),
        prepare=lambda engine, voice: BackendCandidate(
            engine, voice, object(), lambda: discarded.append(True)
        ),
    )
    active_backend = manager.current()

    result = controller.apply_settings(
        ENGINE,
        "alt+backtick",
        "26",
        "0",
        None,
        multilingual_language="es",
        multilingual_exaggeration=1.1,
        multilingual_cfg_weight=0.2,
    )

    assert result.applied is False
    assert controller.state.settings == before
    assert manager.current() is active_backend
    assert discarded == [True]


def test_switching_engines_keeps_multilingual_preferences():
    controller, _manager, _preparations = _controller()

    multilingual = controller.apply_settings(
        ENGINE,
        "alt+backtick",
        "26",
        "0",
        None,
        multilingual_language="it",
        multilingual_exaggeration=1.7,
        multilingual_cfg_weight=0.3,
    )
    back_to_piper = controller.apply_settings(
        "Piper", "alt+backtick", "26", "0", None
    )
    back_to_multilingual = controller.apply_settings(
        ENGINE, "alt+backtick", "26", "0", None
    )

    assert (
        multilingual.applied
        and back_to_piper.applied
        and back_to_multilingual.applied
    )
    assert controller.state.settings.engine == ENGINE
    assert controller.state.settings.multilingual_language == "it"
    assert controller.state.settings.multilingual_exaggeration == 1.7
    assert controller.state.settings.multilingual_cfg_weight == 0.3


def test_settings_window_shows_multilingual_options_and_hides_nano_device_controls(
    monkeypatch,
):
    from tests.windows_tray.test_settings_window import (
        FakeVar,
        FakeWidget,
        install_fake_tk,
        make_snapshot,
    )
    from piper.multilingual_options import SUPPORTED_LANGUAGES

    settings_window = install_fake_tk(monkeypatch, [])
    monkeypatch.setattr(settings_window.tk, "DoubleVar", FakeVar, raising=False)
    monkeypatch.setattr(settings_window.ttk, "Scale", FakeWidget, raising=False)

    window = settings_window.SettingsWindow(
        object(),
        make_snapshot(engine=ENGINE),
        lambda *_args, **_kwargs: SettingsApplyResult(True),
        lambda: None,
        lambda _text: None,
    )

    assert ENGINE in window.engine_combo.kwargs["values"]
    assert window.nano_voice_frame.hidden is False
    assert window.chatterbox_device_controls.hidden is True
    assert window.multilingual_options_frame.hidden is False
    assert window.multilingual_language_combo.kwargs["values"] == tuple(
        SUPPORTED_LANGUAGES.values()
    )
    assert window.multilingual_exaggeration_scale.kwargs["from_"] == 0.25
    assert window.multilingual_exaggeration_scale.kwargs["to"] == 2.0
    assert window.multilingual_cfg_weight_scale.kwargs["from_"] == 0.0
    assert window.multilingual_cfg_weight_scale.kwargs["to"] == 1.0
    assert window.multilingual_exaggeration_value_var.get() == "0.5"
    assert window.multilingual_cfg_weight_value_var.get() == "0.5"

    window.engine_var.set("Chatterbox Nano")
    window._refresh_voice_controls()

    assert window.nano_voice_frame.hidden is False
    assert window.chatterbox_device_controls.hidden is False
    assert window.multilingual_options_frame.hidden is True


def test_settings_window_forwards_multilingual_values(monkeypatch):
    from tests.windows_tray.test_settings_window import (
        FakeVar,
        FakeWidget,
        install_fake_tk,
        make_snapshot,
    )

    settings_window = install_fake_tk(monkeypatch, [])
    monkeypatch.setattr(settings_window.tk, "DoubleVar", FakeVar, raising=False)
    monkeypatch.setattr(settings_window.ttk, "Scale", FakeWidget, raising=False)
    monkeypatch.setattr(
        settings_window.threading,
        "Thread",
        lambda target, **_kwargs: SimpleNamespace(start=target),
    )
    callbacks = []
    seen = []

    class Owner:
        def cancel_nano_settings(self):
            pass

        def apply(self, *args, **kwargs):
            seen.append((args, kwargs))
            return SettingsApplyResult(True)

    owner = Owner()
    window = settings_window.SettingsWindow(
        object(),
        make_snapshot(engine=ENGINE),
        owner.apply,
        lambda: None,
        lambda _text: None,
    )
    window.engine_var.set(ENGINE)
    window.multilingual_language_var.set("French")
    window.multilingual_exaggeration_var.set(1.25)
    window.multilingual_cfg_weight_var.set(0.8)
    window.window.after = lambda _delay, callback: callbacks.append(callback)

    window._apply()
    callbacks.pop(0)()

    assert len(seen) == 1
    args, kwargs = seen[0]
    assert args[0] == ENGINE
    assert kwargs["multilingual_language"] == "fr"
    assert kwargs["multilingual_exaggeration"] == 1.25
    assert kwargs["multilingual_cfg_weight"] == 0.8

