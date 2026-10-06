from types import SimpleNamespace
from threading import Event
import pytest
from piper.windows_tray import app
from piper.windows_tray.backend_manager import BackendPreparationError


def test_configured_turbo_backend_forwards_reference_clip(monkeypatch):
    calls = []
    monkeypatch.setattr(
        app,
        "_prepare_turbo_backend",
        lambda *a, **k: calls.append((a, k)) or "candidate",
        raising=False,
    )
    settings = SimpleNamespace(
        chatterbox_custom_voice_enabled=True, chatterbox_reference_clip="reference.wav"
    )
    cancel = Event()
    assert app._prepare_configured_turbo_backend(settings, cancel) == "candidate"
    assert calls == [((cancel,), {"reference_clip": "reference.wav"})]


def test_turbo_installation_uses_separate_local_root(monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert app._turbo_root() == tmp_path / "Piper" / "ChatterboxTurbo"


def test_gpu_failure_discards_client_and_preserves_explanation(monkeypatch):
    from piper.windows_tray import turbo_client

    closed = []

    def fail(_):
        raise RuntimeError("NVIDIA GPU with CUDA is required")

    client = SimpleNamespace(ensure_ready=fail, shutdown=lambda: closed.append(True))
    monkeypatch.setattr(
        app, "_prepare_turbo_installation", lambda: object(), raising=False
    )
    monkeypatch.setattr(turbo_client, "TurboWorkerClient", lambda *a, **k: client)
    with pytest.raises(BackendPreparationError, match="NVIDIA GPU"):
        app._prepare_turbo_backend()
    assert closed == [True]


def test_saved_turbo_engine_starts_in_background_and_switches_backend(monkeypatch):
    from tests.windows_tray.test_app_foundation import _patch_primary_app
    from piper.turbo_options import ENGINE
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
        ENGINE, "default", SimpleNamespace(device_message="GPU (CUDA)")
    )
    monkeypatch.setattr(
        app,
        "_prepare_configured_turbo_backend",
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
        assert controllers[0]._backend_manager.current_identity() == (ENGINE, "default")
        assert (
            controllers[0].settings_window_snapshot().chatterbox_device_message
            == "GPU (CUDA)"
        )

    ui.root.mainloop = mainloop
    assert app.run_app([]) == 0
