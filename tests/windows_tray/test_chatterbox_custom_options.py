from dataclasses import asdict
import json
from pathlib import Path
from types import SimpleNamespace
import wave

import pytest

from piper.windows_tray.backend_manager import (
    BackendCandidate,
    BackendManager,
    BackendPreparationError,
)
from piper.windows_tray.controller import Controller, SettingsWindowSnapshot
from piper.windows_tray.settings import TraySettings, load_settings, save_settings


def test_custom_voice_settings_default_and_round_trip(tmp_path):
    assert TraySettings().chatterbox_custom_voice_enabled is False
    assert TraySettings().chatterbox_reference_clip == ""

    path = tmp_path / "settings.json"
    settings = TraySettings(
        chatterbox_custom_voice_enabled=True,
        chatterbox_reference_clip=str(tmp_path / "reference.wav"),
    )

    save_settings(settings, path)

    assert load_settings(path).settings == settings


def test_old_settings_default_custom_voice_fields_to_safe_values(tmp_path):
    payload = asdict(TraySettings())
    payload.pop("chatterbox_custom_voice_enabled", None)
    payload.pop("chatterbox_reference_clip", None)
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = load_settings(path)

    assert result.source == "loaded"
    assert result.settings.chatterbox_custom_voice_enabled is False
    assert result.settings.chatterbox_reference_clip == ""


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("chatterbox_custom_voice_enabled", "true"),
        ("chatterbox_custom_voice_enabled", 1),
        ("chatterbox_reference_clip", None),
        ("chatterbox_reference_clip", []),
    ],
)
def test_invalid_custom_voice_settings_are_treated_as_corrupt(tmp_path, field, value):
    path = tmp_path / "settings.json"
    payload = asdict(TraySettings())
    payload[field] = value
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = load_settings(path)

    assert result.source == "corrupt"
    assert result.settings == TraySettings()


def _controller(settings=None, save=None, prepare=None):
    preparations = []
    current_backend = object()

    def prepare_backend(engine, voice):
        preparation_reference = controller.nano_preparation_reference_clip()
        preparations.append((engine, voice, preparation_reference))
        return BackendCandidate(engine, voice, object())

    manager = BackendManager(
        "Chatterbox Nano",
        "default",
        current_backend,
        lambda: None,
        prepare or prepare_backend,
    )
    hotkeys = SimpleNamespace(
        prepare_rebind=lambda _candidate: True,
        commit_rebind=lambda: True,
        rollback_rebind=lambda: True,
    )
    controller = Controller(
        settings=settings or TraySettings(engine="Chatterbox Nano"),
        save_settings=save or (lambda _settings: None),
        hotkeys=hotkeys,
        backend_manager=manager,
    )
    return controller, manager, preparations


def _write_reference_wav(path: Path, seconds=6):
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x01\x00" * (16000 * seconds))
    return path


def test_snapshot_carries_custom_voice_selection():
    clip = str(Path("C:/Piper/reference.wav"))
    controller = Controller(
        settings=TraySettings(
            engine="Chatterbox Nano",
            chatterbox_custom_voice_enabled=True,
            chatterbox_reference_clip=clip,
        )
    )

    snapshot = controller.settings_window_snapshot()

    assert snapshot.chatterbox_custom_voice_enabled is True
    assert snapshot.chatterbox_reference_clip == clip


def test_custom_voice_toggle_prepares_requested_clip_before_commit(monkeypatch, tmp_path):
    clip = _write_reference_wav(tmp_path / "voice.wav")
    saved = []
    controller, manager, preparations = _controller(save=saved.append)

    result = controller.apply_settings(
        "Chatterbox Nano",
        "alt+backtick",
        "26",
        "0",
        None,
        "af_heart",
        chatterbox_custom_voice_enabled=True,
        chatterbox_reference_clip=str(clip),
    )

    assert result.applied is True
    assert preparations == [("Chatterbox Nano", "default", str(clip))]
    assert controller.state.settings.chatterbox_custom_voice_enabled is True
    assert controller.state.settings.chatterbox_reference_clip == str(clip)
    assert result.snapshot.chatterbox_custom_voice_enabled is True
    assert manager.current() is not None
    assert saved[-1] == controller.state.settings
    assert controller.nano_preparation_reference_clip() == str(clip)


def test_disabling_custom_voice_prepares_default_and_keeps_saved_clip(monkeypatch, tmp_path):
    clip = _write_reference_wav(tmp_path / "voice.wav")
    settings = TraySettings(
        engine="Chatterbox Nano",
        chatterbox_custom_voice_enabled=True,
        chatterbox_reference_clip=str(clip),
    )
    controller, _manager, preparations = _controller(settings=settings)

    result = controller.apply_settings(
        "Chatterbox Nano",
        "alt+backtick",
        "26",
        "0",
        None,
        "af_heart",
        chatterbox_custom_voice_enabled=False,
        chatterbox_reference_clip=str(clip),
    )

    assert result.applied is True
    assert preparations == [("Chatterbox Nano", "default", None)]
    assert controller.state.settings.chatterbox_custom_voice_enabled is False
    assert controller.state.settings.chatterbox_reference_clip == str(clip)


def test_missing_enabled_reference_is_rejected_before_backend_preparation(tmp_path):
    saved = []
    controller, manager, preparations = _controller(save=saved.append)

    result = controller.apply_settings(
        "Chatterbox Nano",
        "alt+backtick",
        "26",
        "0",
        None,
        "af_heart",
        chatterbox_custom_voice_enabled=True,
        chatterbox_reference_clip=str(tmp_path / "missing.wav"),
    )

    assert result.applied is False
    assert "reference_clip" in result.error_map()
    assert preparations == []
    assert saved == []
    assert controller.state.settings.chatterbox_custom_voice_enabled is False
    assert manager.current() is not None


def test_preparation_reference_uses_requested_value_then_saved_choice():
    controller, _manager, _preparations = _controller(
        settings=TraySettings(
            engine="Chatterbox Nano",
            chatterbox_custom_voice_enabled=True,
            chatterbox_reference_clip="saved.wav",
        )
    )

    assert controller.nano_preparation_reference_clip() == "saved.wav"
    controller._nano_preparation_context.reference_clip = None
    assert controller.nano_preparation_reference_clip() is None
    controller._nano_preparation_context.reference_clip = "requested.wav"
    assert controller.nano_preparation_reference_clip() == "requested.wav"


def test_settings_window_shows_reference_import_and_custom_voice_toggle(monkeypatch):
    from tests.windows_tray.test_settings_window import install_fake_tk

    module = install_fake_tk(monkeypatch, [])
    window = module.SettingsWindow(
        object(),
        SettingsWindowSnapshot(
            engine="Chatterbox Nano",
            chatterbox_custom_voice_enabled=True,
            chatterbox_reference_clip="C:/Piper/voice.wav",
        ),
        lambda *_args, **_kwargs: None,
        lambda: None,
        lambda _text: None,
        lambda: True,
    )

    assert window.chatterbox_custom_voice_var.get() is True
    assert window.reference_clip_name_var.get() == "voice.wav"
    assert window.import_reference_clip_button.kwargs["text"] == "Import reference clip…"


def test_preparation_failure_keeps_existing_custom_voice_and_saved_settings(
    tmp_path,
):
    clip = _write_reference_wav(tmp_path / "new.wav")
    original = TraySettings(
        engine="Chatterbox Nano",
        chatterbox_custom_voice_enabled=False,
        chatterbox_reference_clip="old.wav",
    )
    saved = []

    def fail_preparation(engine, voice):
        raise BackendPreparationError("worker not ready")

    controller, manager, _ = _controller(
        settings=original, save=saved.append, prepare=fail_preparation
    )

    result = controller.apply_settings(
        "Chatterbox Nano",
        "alt+backtick",
        "26",
        "0",
        None,
        "af_heart",
        chatterbox_custom_voice_enabled=True,
        chatterbox_reference_clip=str(clip),
    )

    assert result.applied is False
    assert "engine" in result.error_map()
    assert controller.state.settings is original
    assert manager.current() is not None
    assert saved == []


def test_save_failure_discards_prepared_custom_voice_and_keeps_old_backend(tmp_path):
    clip = _write_reference_wav(tmp_path / "new.wav")
    closed = []
    backend = object()
    manager = BackendManager(
        "Chatterbox Nano",
        "default",
        backend,
        lambda: None,
        lambda engine, voice: BackendCandidate(
            engine, voice, object(), lambda: closed.append(True)
        ),
    )
    controller = Controller(
        settings=TraySettings(engine="Chatterbox Nano"),
        save_settings=lambda _settings: (_ for _ in ()).throw(OSError("disk full")),
        hotkeys=SimpleNamespace(
            prepare_rebind=lambda _candidate: True,
            commit_rebind=lambda: True,
            rollback_rebind=lambda: True,
        ),
        backend_manager=manager,
    )

    result = controller.apply_settings(
        "Chatterbox Nano",
        "alt+backtick",
        "26",
        "0",
        None,
        "af_heart",
        chatterbox_custom_voice_enabled=True,
        chatterbox_reference_clip=str(clip),
    )

    assert result.applied is False
    assert controller.state.settings.chatterbox_custom_voice_enabled is False
    assert manager.current() is backend
    assert closed == [True]


def test_import_failure_preserves_current_reference_selection(monkeypatch):
    from tests.windows_tray.test_settings_window import install_fake_tk

    module = install_fake_tk(monkeypatch, [])
    monkeypatch.setattr(module, "choose_reference_clip", lambda _parent: Path("new.wav"))
    monkeypatch.setattr(
        module,
        "import_managed_reference_clip",
        lambda _source: (_ for _ in ()).throw(
            ValueError("The reference clip must be longer than 5 seconds.")
        ),
        raising=False,
    )
    monkeypatch.setattr(
        module.threading,
        "Thread",
        lambda target, **_kwargs: SimpleNamespace(start=target),
    )
    window = module.SettingsWindow(
        object(),
        SettingsWindowSnapshot(
            chatterbox_reference_clip="C:/Piper/old.wav",
        ),
        lambda *_args, **_kwargs: None,
        lambda: None,
        lambda _text: None,
        lambda: True,
    )
    callbacks = []
    window.window.after = lambda _delay, callback: callbacks.append(callback)

    window._choose_reference_clip()
    callbacks.pop(0)()

    assert window.pending_reference_clip is None
    assert window.displayed_reference_clip == "C:/Piper/old.wav"
    assert window.reference_clip_name_var.get() == "old.wav"
    assert "longer than 5 seconds" in window.error_text("reference_clip")


def test_apply_waits_for_reference_import_to_finish(monkeypatch):
    from tests.windows_tray.test_settings_window import install_fake_tk

    module = install_fake_tk(monkeypatch, [])
    calls = []
    window = module.SettingsWindow(
        object(),
        SettingsWindowSnapshot(),
        lambda *args, **kwargs: calls.append((args, kwargs))
        or module.SettingsApplyResult(True),
        lambda: None,
        lambda _text: None,
        lambda: True,
    )
    window._reference_import_pending = True

    window._apply()

    assert calls == []
    assert "Wait for the reference clip import" in window.error_text("reference_clip")


def test_reference_import_cannot_start_during_backend_apply(monkeypatch):
    from tests.windows_tray.test_settings_window import install_fake_tk

    module = install_fake_tk(monkeypatch, [])
    choose_calls = []
    monkeypatch.setattr(
        module,
        "choose_reference_clip",
        lambda _parent: choose_calls.append(True) or Path("new.wav"),
    )
    monkeypatch.setattr(
        module,
        "import_managed_reference_clip",
        lambda source: source,
    )
    monkeypatch.setattr(
        module.threading,
        "Thread",
        lambda target, **_kwargs: SimpleNamespace(start=target),
    )
    window = module.SettingsWindow(
        object(),
        SettingsWindowSnapshot(engine="Chatterbox Nano"),
        lambda *_args, **_kwargs: None,
        lambda: None,
        lambda _text: None,
        lambda: True,
    )
    window.window.after = lambda _delay, _callback: None
    window._apply_in_progress = True

    window._choose_reference_clip()

    assert choose_calls == []


def test_saved_startup_custom_voice_is_forwarded_to_nano_backend(monkeypatch):
    import piper.windows_tray.app as app

    settings = TraySettings(
        engine="Chatterbox Nano",
        chatterbox_custom_voice_enabled=True,
        chatterbox_reference_clip="C:/Piper/custom.wav",
    )
    calls = []
    monkeypatch.setattr(
        app,
        "_prepare_nano_backend",
        lambda cancel_event=None, device="cpu", **kwargs: calls.append(
            (cancel_event, device, kwargs)
        ),
    )
    cancel_event = object()

    app._prepare_configured_nano_backend(
        settings,
        cancel_event=cancel_event,
        record_timing=lambda _stage, operation: operation(),
    )

    assert calls == [
        (cancel_event, "cpu", {"reference_clip": "C:/Piper/custom.wav"})
    ]


def test_default_voice_startup_omits_reference_argument(monkeypatch):
    import piper.windows_tray.app as app

    calls = []
    monkeypatch.setattr(
        app,
        "_prepare_nano_backend",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    cancel_event = object()

    app._prepare_configured_nano_backend(
        TraySettings(engine="Chatterbox Nano"),
        cancel_event=cancel_event,
        record_timing=lambda _stage, operation: operation(),
    )

    assert calls == [((cancel_event,), {"device": "cpu"})]
