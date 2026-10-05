"""Turbo integration and failed apply rollback."""

from pathlib import Path
from types import SimpleNamespace

from piper.turbo_options import ENGINE
from piper.windows_tray.backend_manager import (
    BackendCandidate,
    BackendManager,
    BackendPreparationError,
)
from piper.windows_tray.controller import Controller, SettingsApplyResult
from piper.windows_tray.settings import TraySettings


def _controller(save=None, prepare=None):
    preparations = []

    def prepare_backend(engine, voice):
        preparations.append((engine, voice))
        return (
            prepare(engine, voice)
            if prepare
            else BackendCandidate(engine, voice, object())
        )

    manager = BackendManager("Piper", "old", object(), lambda: None, prepare_backend)
    hotkeys = SimpleNamespace(
        prepare_rebind=lambda _: True,
        commit_rebind=lambda: True,
        rollback_rebind=lambda: True,
    )
    controller = Controller(
        settings=TraySettings(piper_voice="old"),
        save_settings=save or (lambda _: None),
        hotkeys=hotkeys,
        backend_manager=manager,
    )
    controller._resolve_voice = lambda reference: Path(reference)
    return controller, manager, preparations


def test_turbo_apply_selects_default_voice_and_saves_settings():
    saved = []
    controller, manager, preparations = _controller(save=saved.append)
    result = controller.apply_settings(ENGINE, "alt+backtick", "26", "0", None)
    assert result.applied
    assert preparations == [(ENGINE, "default")]
    assert manager.current_identity() == (ENGINE, "default")
    assert result.snapshot.engine == ENGINE
    assert saved[-1] == controller.state.settings


def test_turbo_preparation_failure_preserves_backend_and_settings():
    def fail(engine, voice):
        raise BackendPreparationError("CUDA initialization failed")

    controller, manager, preparations = _controller(prepare=fail)
    before, active = controller.state.settings, manager.current()
    result = controller.apply_settings(ENGINE, "alt+backtick", "26", "0", None)
    assert not result.applied
    assert "CUDA" in result.error_map()["engine"]
    assert controller.state.settings == before
    assert manager.current() is active
    assert preparations == [(ENGINE, "default")]


def test_turbo_save_failure_discards_candidate_and_keeps_backend():
    discarded = []

    def fail_save(_):
        raise OSError("disk full")

    controller, manager, _ = _controller(
        save=fail_save,
        prepare=lambda engine, voice: BackendCandidate(
            engine, voice, object(), lambda: discarded.append(True)
        ),
    )
    before, active = controller.state.settings, manager.current()
    result = controller.apply_settings(ENGINE, "alt+backtick", "26", "0", None)
    assert not result.applied
    assert controller.state.settings == before
    assert manager.current() is active
    assert discarded == [True]


def test_switching_between_piper_nano_and_turbo():
    controller, manager, _ = _controller()
    for engine in (ENGINE, "Chatterbox Nano", "Piper", ENGINE):
        result = controller.apply_settings(engine, "alt+backtick", "26", "0", None)
        assert result.applied
        assert controller.state.settings.engine == engine
    assert manager.current_identity() == (ENGINE, "default")


def test_turbo_voice_controls_have_no_retired_options(monkeypatch):
    from tests.windows_tray.test_settings_window import install_fake_tk, make_snapshot

    module = install_fake_tk(monkeypatch, [])
    window = module.SettingsWindow(
        object(),
        make_snapshot(engine=ENGINE),
        lambda *a, **k: SettingsApplyResult(True),
        lambda: None,
        lambda text: None,
    )
    assert window.engine_combo.kwargs["values"] == ("Piper", "Chatterbox Nano", ENGINE)
    assert not window.nano_voice_frame.hidden
    assert window.chatterbox_device_controls.hidden
    assert not window.turbo_info_frame.hidden
    assert not hasattr(window, "multilingual_language_combo")
    assert not hasattr(window, "multilingual_exaggeration_scale")
    assert not hasattr(window, "multilingual_cfg_weight_scale")
    window.engine_var.set("Chatterbox Nano")
    window._refresh_voice_controls()
    assert not window.chatterbox_device_controls.hidden
    assert window.turbo_info_frame.hidden


def test_turbo_apply_prepares_managed_custom_voice(monkeypatch, tmp_path):
    from tests.windows_tray.test_chatterbox_reference_worker import _write_clip

    clip = _write_clip(tmp_path / "voice.wav").resolve()
    seen = []
    controller = None

    def prepare(engine, voice):
        seen.append(controller.nano_preparation_reference_clip())
        return BackendCandidate(engine, voice, object())

    controller, manager, _ = _controller(prepare=prepare)
    result = controller.apply_settings(
        ENGINE,
        "alt+backtick",
        "26",
        "0",
        None,
        chatterbox_custom_voice_enabled=True,
        chatterbox_reference_clip=str(clip),
    )
    assert result.applied
    assert seen == [str(clip)]
    assert manager.current_identity() == (ENGINE, "default")
    assert controller.state.settings.chatterbox_reference_clip == str(clip)


def test_turbo_settings_apply_sends_no_retired_options(monkeypatch):
    from tests.windows_tray.test_settings_window import install_fake_tk, make_snapshot

    module = install_fake_tk(monkeypatch, [])
    seen, callbacks = [], []

    class Owner:
        def cancel_nano_settings(self):
            pass

        def apply(self, *args, **kwargs):
            seen.append((args, kwargs))
            return SettingsApplyResult(True)

    owner = Owner()
    monkeypatch.setattr(
        module.threading,
        "Thread",
        lambda target, **kwargs: SimpleNamespace(start=target),
    )
    window = module.SettingsWindow(
        object(),
        make_snapshot(engine=ENGINE),
        owner.apply,
        lambda: None,
        lambda text: None,
    )
    window.window.after = lambda delay, callback: callbacks.append(callback)
    window._apply()
    callbacks.pop(0)()
    args, kwargs = seen[0]
    assert args[0] == ENGINE
    assert set(kwargs) == {
        "cancel_event",
        "chatterbox_custom_voice_enabled",
        "chatterbox_reference_clip",
        "stop_tts_hotkey",
        "pause_resume_hotkey",
    }
