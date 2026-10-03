from pathlib import Path
import pytest
from piper.windows_tray.settings import TraySettings, save_settings, load_settings
from piper.windows_tray.controller import Controller
from piper.windows_tray.backend_manager import (
    BackendCandidate,
    BackendManager,
    BackendPreparationError,
)


class Hotkeys:
    def prepare_rebind(self, candidate):
        return True

    def commit_rebind(self):
        return True

    def rollback_rebind(self):
        return True


def controller(prepare, save=lambda settings: None):
    manager = BackendManager("Piper", "old", object(), lambda: None, prepare)
    instance = Controller(
        settings=TraySettings(piper_voice="old", kokoro_voice="af_heart"),
        save_settings=save,
        hotkeys=Hotkeys(),
        backend_manager=manager,
    )
    instance.configure_runtime(resolve_voice=lambda reference: Path(reference))
    return instance, manager


def test_nano_settings_preserve_other_voices(tmp_path):
    path = tmp_path / "settings.json"
    settings = TraySettings(
        engine="Chatterbox Nano", piper_voice="saved.onnx", kokoro_voice="af_bella"
    )
    save_settings(settings, path)
    assert load_settings(path).settings == settings


def test_nano_switch_uses_default_voice():
    calls = []
    c, manager = controller(
        lambda engine, voice: calls.append((engine, voice))
        or BackendCandidate(engine, voice, object())
    )
    result = c.apply_settings(
        "Chatterbox Nano", "alt+backtick", "26", "0", None, "af_heart"
    )
    assert result.applied
    assert calls == [("Chatterbox Nano", "default")]
    assert manager.current_identity() == ("Chatterbox Nano", "default")
    assert c.state.settings.piper_voice == "old"


def test_nano_preparation_failure_preserves_piper():
    def fail(engine, voice):
        raise BackendPreparationError("missing")

    c, manager = controller(fail)
    result = c.apply_settings(
        "Chatterbox Nano", "alt+backtick", "26", "0", None, "af_heart"
    )
    assert result.errors == (("engine", "Chatterbox Nano is not available."),)
    assert manager.current_identity() == ("Piper", "old")


def test_nano_save_failure_discards_candidate():
    closed = []

    def fail_save(settings):
        raise OSError("disk")

    c, manager = controller(
        lambda e, v: BackendCandidate(e, v, object(), lambda: closed.append(True)),
        fail_save,
    )
    assert not c.apply_settings(
        "Chatterbox Nano", "alt+backtick", "26", "0", None, "af_heart"
    ).applied
    assert closed == [True]
    assert manager.current_identity() == ("Piper", "old")


def test_nano_startup_success_and_recovery():
    c, manager = controller(lambda e, v: BackendCandidate(e, v, object()))
    statuses = []
    c.configure_runtime(set_tray_status=statuses.append)
    c.begin_nano_startup()
    c.complete_nano_startup(BackendCandidate("Chatterbox Nano", "default", object()))
    assert manager.current_identity() == ("Chatterbox Nano", "default")
    assert statuses[-1] == "Chatterbox Nano is ready"
    c, manager = controller(lambda e, v: BackendCandidate(e, v, object()))
    c.begin_nano_startup()
    c.fail_nano_startup("missing")
    assert manager.current_identity() == ("Piper", "old")
    assert c.settings_window_snapshot().engine == "Piper"


def test_nano_preparation_does_not_hold_controller_lock():
    import threading

    entered, release, responsive = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )

    def prepare(e, v):
        entered.set()
        assert release.wait(2)
        return BackendCandidate(e, v, object())

    c, manager = controller(prepare)
    worker = threading.Thread(
        target=lambda: c.apply_settings(
            "Chatterbox Nano", "alt+backtick", "26", "0", None, "af_heart"
        )
    )
    worker.start()
    assert entered.wait(2)
    reader = threading.Thread(
        target=lambda: (c.settings_window_snapshot(), responsive.set())
    )
    reader.start()
    try:
        assert responsive.wait(0.5)
    finally:
        release.set()
        worker.join(2)
        reader.join(2)


def test_nano_preparation_uses_appdata_payload(monkeypatch, tmp_path):
    from piper.windows_tray import app

    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.delattr(app.sys, "_MEIPASS", raising=False)
    assert app._nano_root() == tmp_path / "Piper" / "ChatterboxNano"


def test_nano_preparation_prefers_verified_bundle(monkeypatch, tmp_path):
    from piper.windows_tray import app
    import sys, types

    bundle = tmp_path / "nano_payload"
    bundle.mkdir()
    monkeypatch.setattr(app.sys, "_MEIPASS", str(tmp_path), raising=False)
    expected = object()
    seen = []
    monkeypatch.setitem(
        sys.modules,
        "piper.nano_assets",
        types.SimpleNamespace(
            inspect_nano_installation=lambda root: seen.append(root) or expected
        ),
    )
    assert app._prepare_nano_installation() is expected
    assert seen == [bundle]


def test_nano_controls_hide_other_voices():
    from piper.windows_tray.settings_window import SettingsWindow
    import types

    class Frame:
        def __init__(self):
            self.visible = False

        def grid(self, **kwargs):
            self.visible = True

        def grid_remove(self):
            self.visible = False

    window = object.__new__(SettingsWindow)
    window.engine_var = types.SimpleNamespace(get=lambda: "Chatterbox Nano")
    window.piper_voice_frame, window.kokoro_voice_frame, window.nano_voice_frame = (
        Frame(),
        Frame(),
        Frame(),
    )
    window._refresh_voice_controls()
    assert window.nano_voice_frame.visible
    assert not window.piper_voice_frame.visible
    assert not window.kokoro_voice_frame.visible


def test_nano_unavailable_kokoro_does_not_change_selection(monkeypatch):
    from tests.windows_tray.test_settings_window import install_fake_tk, make_snapshot
    from piper.windows_tray.controller import SettingsApplyResult

    module = install_fake_tk(monkeypatch, [])
    window = module.SettingsWindow(
        object(),
        make_snapshot(
            engine="Chatterbox Nano", kokoro_unavailable_reason="Kokoro absent"
        ),
        lambda *args: SettingsApplyResult(True),
        lambda: None,
        lambda text: None,
        lambda: True,
    )
    assert window.engine_var.get() == "Chatterbox Nano"


def test_cancel_nano_settings_keeps_old_backend():
    import threading

    entered, release = threading.Event(), threading.Event()
    closed = []

    def prepare(e, v):
        entered.set()
        assert release.wait(2)
        return BackendCandidate(e, v, object(), lambda: closed.append(True))

    c, manager = controller(prepare)
    results = []
    worker = threading.Thread(
        target=lambda: results.append(
            c.apply_settings(
                "Chatterbox Nano", "alt+backtick", "26", "0", None, "af_heart"
            )
        )
    )
    worker.start()
    assert entered.wait(2)
    try:
        c.cancel_nano_settings()
    finally:
        release.set()
        worker.join(2)
    assert not results[0].applied
    assert manager.current_identity() == ("Piper", "old")
    assert closed == [True]


@pytest.mark.parametrize("failure", [False, True])
def test_nano_app_startup_is_background_and_keeps_piper_until_ready(
    monkeypatch, failure
):
    import threading, time
    from types import SimpleNamespace
    from tests.windows_tray.test_app_foundation import _patch_primary_app
    from piper.windows_tray.controller import KokoroStartupState

    events = []
    app, instance, ui, tray = _patch_primary_app(monkeypatch, events)
    monkeypatch.setattr(
        app,
        "load_settings",
        lambda: SimpleNamespace(
            settings=TraySettings(engine="Chatterbox Nano"), source="loaded"
        ),
    )
    controllers = []
    real_controller = Controller
    monkeypatch.setattr(
        app,
        "Controller",
        lambda **kwargs: controllers.append(real_controller(**kwargs))
        or controllers[-1],
    )
    entered, release = threading.Event(), threading.Event()
    preparation_threads = []
    closed = []

    def prepare(cancel_event=None, device="cpu"):
        preparation_threads.append(threading.get_ident())
        entered.set()
        assert release.wait(2)
        if failure:
            raise BackendPreparationError("missing")
        return BackendCandidate(
            "Chatterbox Nano", "default", object(), lambda: closed.append(True)
        )

    monkeypatch.setattr(app, "_prepare_nano_backend", prepare)

    def mainloop():
        assert entered.wait(2)
        c = controllers[0]
        assert c._backend_manager.current_identity()[0] == "Piper"
        assert c.kokoro_startup_state is KokoroStartupState.LOADING
        assert preparation_threads[0] != threading.get_ident()
        release.set()
        deadline = time.monotonic() + 2
        while (
            c.kokoro_startup_state is KokoroStartupState.LOADING
            and time.monotonic() < deadline
        ):
            if ui.root.callbacks:
                ui.root.callbacks.pop(0)()
            time.sleep(0.005)
        assert c.kokoro_startup_state is not KokoroStartupState.LOADING
        assert c._backend_manager.current_identity()[0] == (
            "Piper" if failure else "Chatterbox Nano"
        )

    ui.root.mainloop = mainloop
    assert app.run_app([]) == 0
    assert closed == ([] if failure else [True])


def test_nano_settings_window_applies_off_thread_and_finishes_on_ui(monkeypatch):
    import threading
    from tests.windows_tray.test_settings_window import install_fake_tk, make_snapshot
    from piper.windows_tray.controller import SettingsApplyResult

    module = install_fake_tk(monkeypatch, [])
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    ui_thread = threading.get_ident()
    calls = []

    def apply(*args):
        calls.append(threading.get_ident())
        entered.set()
        assert release.wait(2)
        done.set()
        return SettingsApplyResult(True)

    window = module.SettingsWindow(
        object(),
        make_snapshot(engine="Chatterbox Nano"),
        apply,
        lambda: None,
        lambda text: None,
        lambda: True,
    )
    callbacks = []
    window.window.after = lambda delay, callback: callbacks.append(callback)
    window._apply()
    assert entered.wait(2)
    assert calls[0] != ui_thread
    assert not window._closed
    release.set()
    assert done.wait(2)
    callbacks.pop(0)()
    assert window._closed


def test_newer_nano_apply_supersedes_older_preparation():
    import threading

    entered, release = threading.Event(), threading.Event()
    count = []
    closed = []

    def prepare(e, v):
        count.append(True)
        label = len(count)
        if label == 1:
            entered.set()
            assert release.wait(2)
        return BackendCandidate(e, v, object(), lambda: closed.append(label))

    c, manager = controller(prepare)
    outcomes = []
    old = threading.Thread(
        target=lambda: outcomes.append(
            c.apply_settings(
                "Chatterbox Nano", "alt+backtick", "26", "0", None, "af_heart"
            )
        )
    )
    old.start()
    assert entered.wait(2)
    try:
        assert c.apply_settings(
            "Chatterbox Nano", "alt+backtick", "30", "0", None, "af_heart"
        ).applied
    finally:
        release.set()
        old.join(2)
    assert not outcomes[0].applied
    assert c.state.settings.pitch_percent == 30
    assert closed == [1]
