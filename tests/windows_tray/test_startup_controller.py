from pathlib import Path
import threading
from types import SimpleNamespace

from piper.windows_tray.backend_manager import BackendCandidate
from piper.windows_tray.commands import Command, CommandKind
from piper.windows_tray import controller as controller_module
from piper.windows_tray.controller import Controller
from piper.windows_tray.settings import TraySettings
from piper.windows_tray.voice_manager import VoiceManager
from piper.windows_tray.speech import (
    SpeechEvent,
    SpeechEventKind,
    SpeechPurpose,
    SpeechRequest,
    SpeechWorker,
)


class RecordingSpeechWorker:
    def __init__(self):
        self.submitted = []

    def submit(self, request):
        self.submitted.append(request)
        return True

    def cancel_auxiliary(self):
        pass


class RecordingBackendManager:
    def __init__(self, piper):
        self.piper = piper
        self.current_backend = piper
        self.current_engine = "Piper"
        self.current_voice_id = "old.onnx"
        self.commits = []
        self.discards = []

    def current(self):
        return self.current_backend

    def current_identity(self):
        return self.current_engine, self.current_voice_id

    def commit(self, candidate):
        self.commits.append(candidate)
        self.current_backend = candidate.backend
        self.current_engine = candidate.engine
        self.current_voice_id = candidate.voice_id

    def discard(self, candidate):
        self.discards.append(candidate)


def make_controller(settings=None):
    piper = object()
    speech = RecordingSpeechWorker()
    backend_manager = RecordingBackendManager(piper)
    statuses = []
    controller = Controller(
        settings=settings or TraySettings(engine="Piper"),
        speech_worker=speech,
        backend_manager=backend_manager,
    )
    controller.configure_runtime(show_status=statuses.append)
    return controller, speech, backend_manager, piper, statuses


def test_piper_selected_startup_state_is_ready():
    controller, *_ = make_controller()

    startup_state = getattr(controller_module, "BackendStartupState", None)
    assert startup_state is not None
    assert controller.backend_startup_state is startup_state.READY


def test_begin_nano_startup_marks_loading():
    controller, *_ = make_controller()

    controller.begin_nano_startup()

    assert controller.backend_startup_state is controller_module.BackendStartupState.LOADING


def test_startup_transitions_update_tray_status_and_failure_guidance():
    controller, _speech, _manager, _piper, statuses = make_controller()
    tray_statuses = []
    controller.configure_runtime(set_tray_status=tray_statuses.append)

    controller.begin_nano_startup()
    controller.complete_nano_startup(
        BackendCandidate("Chatterbox Nano", "default", object())
    )
    controller.begin_nano_startup()
    controller.fail_nano_startup("unavailable")

    assert tray_statuses == [
        "Chatterbox Nano is loading",
        "Chatterbox Nano is ready",
        "Chatterbox Nano is loading",
        "Chatterbox Nano unavailable; Piper is ready",
    ]
    assert statuses[-1] == (
        "Chatterbox Nano is unavailable. Piper will continue to be used. "
        "Check the installed Nano payload."
    )


def test_startup_result_cannot_commit_after_shutdown_begins():
    controller, _speech, manager, _piper, _statuses = make_controller()
    candidate = BackendCandidate("Chatterbox Nano", "default", object())
    controller.begin_nano_startup()
    controller.handle(Command(CommandKind.EXIT))

    controller.complete_nano_startup(candidate)

    assert controller.state.shutting_down is True
    assert manager.commits == []
    assert manager.discards == [candidate]


def test_loading_hotkey_announces_once_and_bypasses_capture():
    controller, speech, _manager, piper, _statuses = make_controller()
    capture_calls = []
    controller.configure_runtime(capture=lambda: capture_calls.append(True))
    controller.begin_nano_startup()

    controller.handle(Command(CommandKind.CAPTURE_REQUEST))
    controller.handle(Command(CommandKind.CAPTURE_REQUEST))

    assert capture_calls == []
    assert len(speech.submitted) == 1
    request = speech.submitted[0]
    assert request.text == "Chatterbox Nano is loading, please wait."
    assert request.purpose is SpeechPurpose.STARTUP_STATUS
    assert request.backend_override is piper


def test_capture_enqueued_while_loading_stays_status_request_after_readiness():
    controller, speech, manager, piper, _statuses = make_controller(
        TraySettings(engine="Chatterbox Nano")
    )
    capture_jobs = []
    controller.configure_runtime(capture_submit=capture_jobs.append)
    controller.begin_nano_startup()

    controller.enqueue(Command(CommandKind.CAPTURE_REQUEST))
    queued_capture = controller.drain_once()
    candidate = BackendCandidate("Chatterbox Nano", "default", object())
    controller.complete_nano_startup(candidate)
    controller.handle(queued_capture)

    assert manager.current() is candidate.backend
    assert capture_jobs == []
    assert len(speech.submitted) == 1
    request = speech.submitted[0]
    assert request.purpose is SpeechPurpose.STARTUP_STATUS
    assert request.backend_override is piper


def test_loading_hotkey_can_retry_after_pending_status_is_evicted():
    controller, speech, _manager, _piper, _statuses = make_controller()
    controller.begin_nano_startup()
    controller.handle(Command(CommandKind.CAPTURE_REQUEST))
    first_request = speech.submitted[-1]

    # SpeechWorker reports pending-request eviction through this same queued
    # worker-event path; processing the terminal event releases the guard.
    controller.enqueue_worker_event(
        SpeechEvent(
            SpeechEventKind.CANCELLED,
            first_request.generation,
            purpose=SpeechPurpose.STARTUP_STATUS,
        )
    )
    event_command = controller.drain_once()
    assert event_command is not None
    controller.handle(event_command)

    controller.handle(Command(CommandKind.CAPTURE_REQUEST))

    assert len(speech.submitted) == 2
    assert speech.submitted[-1].purpose is SpeechPurpose.STARTUP_STATUS


def test_cancel_auxiliary_eviction_allows_another_loading_hotkey():
    active_started = threading.Event()
    release_active = threading.Event()

    def synthesize(text):
        if text == "active foreground":
            active_started.set()
            release_active.wait(timeout=2)
        return [SimpleNamespace(audio_int16_bytes=text.encode())]

    piper = SimpleNamespace(
        config=SimpleNamespace(sample_rate=22050), synthesize=synthesize
    )

    class Player:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def play(self, _data):
            return None

        def stop(self):
            return None

    manager = RecordingBackendManager(piper)
    controller = Controller(
        settings=TraySettings(engine="Piper"), backend_manager=manager
    )
    worker = SpeechWorker(
        lambda: piper,
        controller.enqueue_worker_event,
        player_factory=lambda _sample_rate: Player(),
    )
    controller.configure_runtime(speech_worker=worker)

    try:
        worker.submit(SpeechRequest(501, "active foreground"))
        assert active_started.wait(timeout=1)
        controller.begin_nano_startup()
        controller.handle(Command(CommandKind.CAPTURE_REQUEST))
        first_request = worker._pending_startup_status
        assert first_request is not None

        worker.cancel_auxiliary()
        while True:
            event_command = controller.drain_once()
            if event_command is None:
                break
            controller.handle(event_command)

        controller.handle(Command(CommandKind.CAPTURE_REQUEST))

        assert worker._pending_startup_status is not None
        assert worker._pending_startup_status.generation != first_request.generation
    finally:
        release_active.set()
        worker.shutdown()


def test_successful_startup_commits_candidate():
    controller, _speech, manager, _piper, _statuses = make_controller()
    candidate = BackendCandidate("Chatterbox Nano", "default", object())

    controller.begin_nano_startup()
    controller.complete_nano_startup(candidate)

    assert controller.backend_startup_state is controller_module.BackendStartupState.READY
    assert manager.commits == [candidate]


def test_hotkey_after_startup_readiness_requests_capture_with_nano_active():
    controller, _speech, manager, _piper, _statuses = make_controller(
        TraySettings(engine="Chatterbox Nano")
    )
    candidate = BackendCandidate("Chatterbox Nano", "default", object())
    capture_jobs = []
    controller.configure_runtime(
        capture=lambda: None,
        capture_submit=capture_jobs.append,
    )

    controller.begin_nano_startup()
    controller.complete_nano_startup(candidate)
    controller.handle(Command(CommandKind.CAPTURE_REQUEST))

    assert manager.current() is candidate.backend
    assert len(capture_jobs) == 1
    assert controller.backend_startup_state is controller_module.BackendStartupState.READY


def test_successful_nano_startup_clears_live_piper_references():
    controller, _speech, manager, piper, _statuses = make_controller(
        TraySettings(engine="Chatterbox Nano")
    )
    voice_manager = VoiceManager(piper, lambda _reference: None)
    controller.configure_runtime(voice_manager=voice_manager)
    controller.set_voice(Path("old.onnx"), piper)
    candidate = BackendCandidate("Chatterbox Nano", "default", object())

    controller.begin_nano_startup()
    assert controller._startup_piper_backend is piper

    controller.complete_nano_startup(candidate)

    assert manager.current() is candidate.backend
    assert controller.state.voice is None
    assert voice_manager.current() is None
    assert controller._startup_piper_backend is None
    assert controller.state.voice_path == Path("old.onnx")


def test_failed_startup_keeps_piper_and_saved_settings():
    settings = TraySettings(engine="Piper", piper_voice="en_GB-alba-medium")
    controller, _speech, manager, piper, statuses = make_controller(settings)
    before = controller.state.settings

    controller.begin_nano_startup()
    controller.fail_nano_startup("Chatterbox Nano model could not be loaded")

    assert controller.backend_startup_state is controller_module.BackendStartupState.UNAVAILABLE
    assert manager.current() is piper
    assert manager.commits == []
    assert controller.state.settings == before
    assert statuses and "Chatterbox Nano" in statuses[-1]
