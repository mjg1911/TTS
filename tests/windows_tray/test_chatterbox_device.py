from types import SimpleNamespace
from dataclasses import asdict
import json

from piper.windows_tray.settings import TraySettings, load_settings, save_settings
from piper.windows_tray.backend_manager import BackendCandidate
from piper.windows_tray.backend_manager import BackendManager
from piper.windows_tray.controller import Controller


def controller(prepare, save=lambda settings: None):
    manager = BackendManager("Piper", "old", object(), lambda: None, prepare)
    hotkeys = SimpleNamespace(
        prepare_rebind=lambda _: True,
        commit_rebind=lambda: True,
        rollback_rebind=lambda: True,
    )
    instance = Controller(
        settings=TraySettings(piper_voice="old", kokoro_voice="af_heart"),
        save_settings=save,
        hotkeys=hotkeys,
        backend_manager=manager,
    )
    return instance, manager


def test_device_defaults_cpu_and_round_trips(tmp_path):
    assert TraySettings().chatterbox_device == "cpu"
    path = tmp_path / "settings.json"
    settings = TraySettings(chatterbox_device="cuda")
    save_settings(settings, path)
    assert load_settings(path).settings == settings


def test_device_switch_reloads_worker_and_persists():
    requested = []

    def prepare(engine, voice):
        requested.append(c.nano_preparation_device())
        return BackendCandidate(engine, voice, SimpleNamespace(device_message=""))

    saved = []
    c, manager = controller(prepare, saved.append)
    assert c.apply_settings(
        "Chatterbox Nano", "alt+backtick", "26", "0", None, "af_heart"
    ).applied
    assert c.apply_settings(
        "Chatterbox Nano",
        "alt+backtick",
        "26",
        "0",
        None,
        "af_heart",
        chatterbox_device="cuda",
    ).applied
    assert requested == ["cpu", "cuda"]
    assert saved[-1].chatterbox_device == "cuda"
    assert c.settings_window_snapshot().chatterbox_device == "cuda"


def test_unavailable_cuda_message_preserves_preference():
    c, manager = controller(
        lambda e, v: BackendCandidate(
            e, v, SimpleNamespace(device_message="CUDA unavailable; using CPU.")
        )
    )
    notices = []
    c.configure_runtime(show_notification=notices.append)
    result = c.apply_settings(
        "Chatterbox Nano",
        "alt+backtick",
        "26",
        "0",
        None,
        "af_heart",
        chatterbox_device="cuda",
    )
    assert result.applied
    assert result.snapshot.chatterbox_device_message == "CUDA unavailable; using CPU."
    assert c.state.settings.chatterbox_device == "cuda"
    assert notices == ["CUDA unavailable; using CPU."]


def test_invalid_device_does_not_prepare_worker():
    calls = []
    c, manager = controller(lambda e, v: calls.append(v))
    result = c.apply_settings(
        "Chatterbox Nano",
        "alt+backtick",
        "26",
        "0",
        None,
        "af_heart",
        chatterbox_device="mps",
    )
    assert not result.applied
    assert calls == []


def test_older_settings_default_to_cpu(tmp_path):
    data = asdict(TraySettings())
    data.pop("chatterbox_device")
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data))
    result = load_settings(path)
    assert result.source == "loaded"
    assert result.settings.chatterbox_device == "cpu"


def test_device_save_failure_preserves_working_device():
    closed = []
    c, manager = controller(
        lambda e, v: BackendCandidate(e, v, object(), lambda: closed.append(True))
    )
    assert c.apply_settings(
        "Chatterbox Nano", "alt+backtick", "26", "0", None, "af_heart"
    ).applied
    original = manager.current()
    c._save_settings = lambda _: (_ for _ in ()).throw(OSError("disk"))
    result = c.apply_settings(
        "Chatterbox Nano",
        "alt+backtick",
        "26",
        "0",
        None,
        "af_heart",
        chatterbox_device="cuda",
    )
    assert not result.applied
    assert c.state.settings.chatterbox_device == "cpu"
    assert manager.current() is original
    assert closed == [True]


def test_startup_fallback_is_reported():
    c, manager = controller(lambda e, v: None)
    notices = []
    c.configure_runtime(show_notification=notices.append)
    c.begin_nano_startup()
    c.complete_nano_startup(
        BackendCandidate(
            "Chatterbox Nano",
            "default",
            SimpleNamespace(device_message="CUDA unavailable; using CPU."),
        )
    )
    assert notices == ["CUDA unavailable; using CPU."]


def test_gpu_controls_forward_choice_and_keep_fallback_visible(monkeypatch):
    import threading
    from tests.windows_tray.test_settings_window import install_fake_tk, make_snapshot
    from piper.windows_tray.controller import SettingsApplyResult

    module = install_fake_tk(monkeypatch, [])
    monkeypatch.setattr(
        module.threading,
        "Thread",
        lambda target, **kwargs: SimpleNamespace(start=target),
    )
    seen = []
    done = threading.Event()

    class Owner:
        def cancel_nano_settings(self):
            pass

        def apply(self, *args, **kwargs):
            seen.append(kwargs["chatterbox_device"])
            done.set()
            return SettingsApplyResult(
                True,
                snapshot=make_snapshot(
                    engine="Chatterbox Nano",
                    chatterbox_device="cuda",
                    chatterbox_device_message="CUDA unavailable; using CPU.",
                ),
            )

    window = module.SettingsWindow(
        object(),
        make_snapshot(engine="Chatterbox Nano"),
        Owner().apply,
        lambda: None,
        lambda _: None,
        lambda: True,
    )
    assert window.chatterbox_device_var.get() == "cpu"
    window.chatterbox_device_var.set("cuda")
    callbacks = []
    window.window.after = lambda delay, callback: callbacks.append(callback)
    window._apply()
    assert done.wait(2)
    callbacks.pop(0)()
    assert seen == ["cuda"]
    assert not window.destroyed
    assert window.engine_status_var.get() == "CUDA unavailable; using CPU."
