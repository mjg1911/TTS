from dataclasses import replace
import threading
from threading import Event
from types import SimpleNamespace

from piper.windows_tray.backend_manager import BackendCandidate, BackendPreparationError
from tests.windows_tray.test_nano_integration import controller


def apply(c, **options):
    return c.apply_settings("Supertonic 3", "alt+backtick", "26", "0", None, **options)


def test_switching_supertonic_device_reprepares_and_persists():
    calls = []
    c, manager = controller(lambda e, v: calls.append(c.supertonic_preparation_device())
                            or BackendCandidate(e, v, object()))
    assert apply(c, supertonic_device='cpu').applied
    assert c.state.settings.supertonic_device == 'cpu'
    assert c.settings_window_snapshot().supertonic_device == 'cpu'
    assert apply(c, supertonic_device='cuda').applied
    assert calls == ['cpu', 'cuda']
    assert apply(c, supertonic_device='cuda').applied
    assert calls == ['cpu', 'cuda']
    assert not apply(c, supertonic_device='auto').applied


def test_failed_gpu_switch_keeps_active_supertonic_cpu_and_settings():
    backend = object()
    closed = []
    def prepare(engine, voice):
        if c.supertonic_preparation_device() == 'cuda':
            raise BackendPreparationError('CUDA unavailable')
        return BackendCandidate(engine, voice, backend, lambda: closed.append(True))
    c, manager = controller(prepare)
    assert apply(c, supertonic_device='cpu').applied
    saved = c.state.settings
    result = apply(c, supertonic_device='cuda')
    assert not result.applied
    assert c.state.settings is saved
    assert c.state.settings.supertonic_device == 'cpu'
    assert manager.current() is backend
    assert closed == []
    assert c.supertonic_preparation_device() == 'cpu'


def test_supertonic_switch_uses_selected_style_and_language():
    calls = []
    c, manager = controller(
        lambda e, v: calls.append((e, v, c.supertonic_preparation_language()))
        or BackendCandidate(e, v, object())
    )
    result = apply(c, supertonic_voice="F3", supertonic_language="nl")
    assert result.applied
    assert calls == [("Supertonic 3", "F3", "nl")]
    assert manager.current_identity() == ("Supertonic 3", "F3")
    assert result.snapshot.supertonic_voice == "F3"
    assert result.snapshot.supertonic_language == "nl"
    assert c.state.settings.piper_voice == "old"
    assert apply(c, supertonic_language="en").applied
    assert calls[-1] == ("Supertonic 3", "F3", "en")
    assert len(calls) == 2


def test_failed_supertonic_preparation_keeps_active_backend_and_settings():
    def fail(e, v):
        raise BackendPreparationError("CUDA unavailable")

    c, manager = controller(fail)
    old = c.state.settings
    result = apply(c)
    assert not result.applied
    assert "CUDA" in result.errors[0][1]
    assert manager.current_identity() == ("Piper", "old")
    assert c.state.settings is old


def test_supertonic_save_failure_releases_worker_and_keeps_settings():
    closed = []

    def save(_settings):
        raise OSError('disk full')

    c, manager = controller(
        lambda e, v: BackendCandidate(e, v, object(), lambda: closed.append(True)), save
    )
    old = c.state.settings
    assert not apply(c, supertonic_voice='F2').applied
    assert manager.current_identity() == ('Piper', 'old')
    assert c.state.settings is old
    assert closed == [True]


def test_cancelled_supertonic_preparation_discards_candidate():
    event = threading.Event()
    closed = []

    def prepare(e, v):
        event.set()
        return BackendCandidate(e, v, object(), lambda: closed.append(True))

    c, manager = controller(prepare)
    assert not apply(c, cancel_event=event).applied
    assert manager.current_identity() == ('Piper', 'old')
    assert closed == [True]


def test_invalid_supertonic_preferences_do_not_start_worker():
    calls = []
    c, manager = controller(lambda e, v: calls.append((e, v)))
    assert not apply(c, supertonic_voice='F9').applied
    assert not apply(c, supertonic_language='unsupported').applied
    assert calls == []


def test_supertonic_readiness_does_not_hold_ui_lock():
    entered, release = threading.Event(), threading.Event()

    def prepare(e, v):
        entered.set()
        assert release.wait(3)
        return BackendCandidate(e, v, object())

    c, manager = controller(prepare)
    worker = threading.Thread(target=lambda: apply(c))
    worker.start()
    try:
        assert entered.wait(2)
        assert c._state_lock.acquire(timeout=0.5)
        c._state_lock.release()
    finally:
        release.set()
        worker.join(3)


def test_supertonic_startup_names_engine_and_recovers_to_piper():
    c, manager = controller(lambda e, v: BackendCandidate(e, v, object()))
    c.state.settings = replace(c.state.settings, engine="Supertonic 3")
    messages = []
    c.configure_runtime(show_status=messages.append)
    c.begin_nano_startup()
    assert c._startup_engine == "Supertonic 3"
    c.fail_nano_startup("CUDA unavailable")
    assert "Supertonic 3" in messages[-1]
    assert c.state.settings.engine == "Piper"


def test_configured_supertonic_preparation_forwards_voice_and_language(monkeypatch):
    from types import SimpleNamespace
    from piper.windows_tray import app

    calls = []
    monkeypatch.setattr(
        app,
        "_prepare_supertonic_backend",
        lambda *a, **k: calls.append((a, k)) or "candidate",
        raising=False,
    )
    settings = SimpleNamespace(supertonic_voice="F2", supertonic_language="nl", supertonic_device="cpu")
    event = threading.Event()
    assert app._prepare_configured_supertonic_backend(settings, event) == "candidate"
    assert calls == [((event,), {"voice": "F2", "language": "nl", "device": "cpu"})]


def test_saved_supertonic_engine_starts_in_background_and_switches_backend(monkeypatch):
    from tests.windows_tray.test_app_foundation import _patch_primary_app
    from piper.supertonic_options import ENGINE
    from piper.windows_tray.settings import TraySettings
    from piper.windows_tray.backend_manager import BackendCandidate

    events = []
    app, _, ui, _ = _patch_primary_app(monkeypatch, events)
    settings = TraySettings(engine=ENGINE)
    monkeypatch.setattr(
        app,
        "load_settings",
        lambda: SimpleNamespace(settings=settings, source="loaded"),
    )
    calls, controllers = [], []
    candidate = BackendCandidate(
        ENGINE, "M1", SimpleNamespace(device_message="GPU (CUDA)")
    )
    monkeypatch.setattr(
        app,
        "_prepare_configured_supertonic_backend",
        lambda *a, **k: calls.append((a, k)) or candidate,
    )
    original = app.Controller
    monkeypatch.setattr(
        app,
        "Controller",
        lambda *a, **k: controllers.append(original(*a, **k)) or controllers[-1],
    )
    monkeypatch.setattr(
        app,
        "_build_speech_worker",
        lambda *a: SimpleNamespace(
            submit=lambda *a: False,
            shutdown=lambda: None,
            cancel_active=lambda *a: None,
            cancel_auxiliary=lambda: None,
        ),
    )

    class Coordinator:
        def __init__(self, job, logger, engine_label=None):
            assert engine_label == ENGINE
            self.job = job
            self.result = None

        def start(self):
            result, _ = self.job(Event(), lambda stage, action: action())
            self.result = SimpleNamespace(candidate=result, stage_durations={})

        def take_result(self):
            result, self.result = self.result, None
            return result

        def cancel(self):
            pass

    monkeypatch.setattr(app, "BackendStartupCoordinator", Coordinator)

    def mainloop():
        assert calls[0][0] == (settings,)
        ui.root.callbacks.pop(0)()
        ui.root.callbacks.pop(0)()
        assert controllers[0]._backend_manager.current_identity() == (ENGINE, "M1")
        assert (
            controllers[0].settings_window_snapshot().chatterbox_device_message
            == "GPU (CUDA)"
        )

    ui.root.mainloop = mainloop
    assert app.run_app([]) == 0
