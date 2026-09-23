import re
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from piper.windows_tray.capture import CaptureResult, CaptureStatus
from piper.windows_tray.commands import CommandKind
from piper.windows_tray.controller import CaptureCompletion, Controller


class FakeRoot:
    def __init__(self, events):
        self.events = events
        self.callbacks = []

    def after(self, delay, callback):
        self.events.append(("after", delay))
        self.callbacks.append(callback)

    def mainloop(self):
        self.events.append("mainloop")
        self.callbacks.pop(0)()

    def quit(self):
        self.events.append("quit")

    def destroy(self):
        self.events.append("destroy")


class FakeUi:
    def __init__(self, events):
        self.events = events
        self.root = FakeRoot(events)
        self.statuses = []
        self.last_text_calls = []

    def choose_voice_model(self):
        return None

    def show_status(self, message):
        self.statuses.append(message)

    def show_last_text(self, text):
        self.last_text_calls.append(text)

    def prompt_pitch(self, _current):
        return None

    def prompt_speed(self, _current):
        return None


class FakeInstance:
    def __init__(self, events):
        self.events = events
        self.role = None

    def acquire(self):
        self.events.append("acquire")
        return self.role

    def close(self):
        self.events.append("instance.close")

    def start_activation_watch(self, callback):
        self.events.append("watch")


class FakeTray:
    def __init__(self, _path, _enqueue):
        self.events = []

    def start(self):
        self.events.append("start")

    def stop(self):
        self.events.append("stop")

    def set_status(self, _text):
        pass

    def ensure_visible(self):
        self.events.append("ensure")

    def show_notification(self, message):
        self.events.append(("notification", message))


class FakePowerListener:
    def start(self, _callback):
        pass

    def stop(self):
        pass


class FakeHotkeys:
    def __init__(self, events):
        self.events = events
        self.callbacks = None
        self.failure_callback = None
        self.started_spec = None

    def set_failure_callback(self, callback):
        self.failure_callback = callback

    def start(self, spec, on_capture, on_cancel):
        self.events.append(("hotkeys.start", spec.canonical))
        self.started_spec = spec.canonical
        self.callbacks = (on_capture, on_cancel)

    def stop(self):
        self.events.append("hotkeys.stop")


def test_hotkey_callbacks_enqueue_capture_and_cancel_commands():
    commands = []
    hotkeys = FakeHotkeys([])
    controller = Controller(capture_submit=lambda _job: None)
    hotkeys.start(
        SimpleNamespace(canonical="ctrl+q"),
        lambda: commands.append((CommandKind.CAPTURE_REQUEST, None)),
        lambda: commands.append((CommandKind.CANCEL_REQUEST, None)),
    )

    hotkeys.callbacks[0]()
    hotkeys.callbacks[1]()

    assert [kind for kind, _value in commands] == [
        CommandKind.CAPTURE_REQUEST,
        CommandKind.CANCEL_REQUEST,
    ]


def test_controller_delivers_only_fresh_success_to_last_text():
    jobs = []
    controller = Controller(
        capture=lambda: CaptureResult(CaptureStatus.SUCCESS, "NEW"),
        capture_submit=jobs.append,
    )

    controller.handle(SimpleNamespace(kind=CommandKind.CAPTURE_REQUEST))
    jobs[0]()
    completion = controller.drain_once()
    controller.handle(completion)

    assert controller.state.last_text == "NEW"
    assert controller.state.capture_in_progress is False


def test_capture_failure_preserves_previous_text_without_native_notification():
    notifications = []
    statuses = []
    jobs = []
    controller = Controller(
        capture=lambda: CaptureResult(CaptureStatus.EMPTY),
        capture_submit=jobs.append,
    )
    controller.state.last_text = "previous"
    controller.configure_runtime(
        show_notification=notifications.append,
        show_status=statuses.append,
    )

    controller.handle(SimpleNamespace(kind=CommandKind.CAPTURE_REQUEST))
    jobs[0]()
    controller.handle(controller.drain_once())

    assert notifications == []
    assert statuses == []
    assert controller.state.last_text == "previous"


def test_no_text_capture_does_not_invoke_tk_messagebox(monkeypatch):
    import piper.windows_tray.ui as ui

    calls = []
    monkeypatch.setattr(
        ui.messagebox,
        "showinfo",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    notifications = []
    controller = Controller(capture_submit=lambda _job: None)
    controller.configure_runtime(show_notification=notifications.append)

    controller.handle(SimpleNamespace(kind=CommandKind.CAPTURE_REQUEST))
    generation = controller.state.capture_generation
    controller.handle(
        SimpleNamespace(
            kind=CommandKind.CAPTURE_FAILED,
            value=CaptureCompletion(
                generation,
                CaptureResult(CaptureStatus.EMPTY),
            ),
        )
    )

    assert notifications == []
    assert calls == []


def test_app_starts_hotkeys_after_voice_setup_and_stops_before_mutex_release(monkeypatch):
    import piper.windows_tray.app as app

    events = []
    instance = FakeInstance(events)
    instance.role = app.InstanceRole.PRIMARY
    ui = FakeUi(events)
    tray = FakeTray(Path("icon.png"), lambda _command: None)
    hotkeys = FakeHotkeys(events)
    controllers = []
    workers = []
    installation = SimpleNamespace(
        voices={"af_heart": object()},
        worker_executable=Path("worker.exe"),
        root=Path("kokoro"),
        manifest_sha256="manifest",
        worker_version="worker-version",
        kokoro_version="kokoro-version",
    )

    class WorkerClient:
        def __init__(self, _config, _voice_id):
            events.append("worker.construct")
            workers.append(self)

        def ensure_ready(self, _cancel_event=None):
            events.append("worker.ready")

        def shutdown(self):
            events.append("worker.shutdown")

    logs = []
    logger = SimpleNamespace(
        warning=lambda *_args: None,
        error=lambda *_args: None,
        exception=lambda *_args: None,
        info=lambda *args: logs.append(args),
    )

    monkeypatch.setattr(app, "SingleInstance", lambda: instance)
    monkeypatch.setattr(
        app,
        "load_settings",
        lambda: SimpleNamespace(settings=app.TraySettings(), source="missing"),
    )
    monkeypatch.setattr(
        app,
        "configure_logging",
        lambda _level: logger,
    )
    monkeypatch.setattr(app, "TkUi", lambda: ui)
    monkeypatch.setattr(
        app,
        "Controller",
        lambda *args, **kwargs: controllers.append(Controller(*args, **kwargs)) or controllers[-1],
    )
    monkeypatch.setattr(
        app,
        "_load_configured_voice",
        lambda _settings, _dirs: events.append("voice") or (Path("voice.onnx"), object()),
    )
    monkeypatch.setattr(
        app,
        "_prepare_kokoro_installation",
        Mock(
            side_effect=lambda _logger: events.append("kokoro.prepare")
            or (installation, None)
        ),
    )
    prepare_kokoro = app._prepare_kokoro_installation
    monkeypatch.setattr(app, "KokoroWorkerClient", WorkerClient)
    monkeypatch.setattr(app, "TrayIcon", lambda _path, _enqueue: tray)
    monkeypatch.setattr(app, "HotkeyManager", lambda: hotkeys)
    monkeypatch.setattr(app, "PowerBroadcastListener", FakePowerListener)

    def mainloop():
        controller = controllers[0]
        prepare_kokoro.assert_not_called()
        assert "kokoro.prepare" not in events
        assert "worker.construct" not in events
        candidate = controller._backend_manager.prepare("Kokoro", "af_heart")
        assert controller._kokoro_voice_ids == ("af_heart",)
        candidate.discard()
        retry_candidate = controller._backend_manager.prepare("Kokoro", "af_heart")
        retry_candidate.discard()
        hotkeys.failure_callback(OSError("GetMessageW returned 0"))
        ui.root.callbacks.pop(0)()
        controller.enqueue(app.Command(app.CommandKind.EXIT))
        ui.root.callbacks.pop(0)()

    ui.root.mainloop = mainloop

    assert app.run_app([]) == 0
    assert events.index("voice") < events.index(("hotkeys.start", "alt+backtick"))
    assert events.index(("hotkeys.start", "alt+backtick")) < events.index(
        "kokoro.prepare"
    )
    assert events.index("kokoro.prepare") < events.index("worker.ready")
    assert events.count("kokoro.prepare") == 1
    assert events.index("hotkeys.stop") < events.index("instance.close")
    assert controllers[0]._log_info == logger.info
    assert controllers[0]._show_notification == tray.show_notification
    logged_messages = [str(value) for item in logs for value in item]
    assert any("stage=piper_voice_load" in message for message in logged_messages)
    assert any("stage=tray_hotkey_ready" in message for message in logged_messages)
    assert not any("kokoro_asset_preparation" in message for message in logged_messages)
    assert not any("kokoro_worker_readiness" in message for message in logged_messages)
    assert ui.statuses == [
        "Piper hotkeys stopped unexpectedly; hotkeys are unavailable."
    ]


@pytest.mark.parametrize("failure_stage", (None, "assets", "worker", "cancel"))
def test_kokoro_startup_keeps_tray_and_hotkeys_available_before_preparation(
    monkeypatch, failure_stage
):
    import piper.windows_tray.app as app

    events = []
    child_processes = []

    class FakeChildProcess:
        def __init__(self):
            self.running = True
            self.terminated = False
            self.wait_calls = 0

        def terminate(self):
            events.append("process.terminate")
            self.terminated = True
            self.running = False

        def wait(self):
            events.append("process.wait")
            assert self.terminated
            self.wait_calls += 1

    class StartupInstance(FakeInstance):
        def close(self):
            assert all(
                not process.running
                and process.terminated
                and process.wait_calls >= 1
                for process in child_processes
            )
            events.append("instance.close")

    instance = StartupInstance(events)
    instance.role = app.InstanceRole.PRIMARY
    ui = FakeUi(events)
    hotkeys = FakeHotkeys(events)
    controllers = []
    workers = []
    initializer_threads = []
    preparation_threads = []
    completion_threads = []
    failure_transition_threads = []
    ready_status_threads = []
    unavailable_status_threads = []
    failure_message_threads = []
    coordination_threads = []
    worker_readiness_entered = threading.Event()
    release_worker_readiness = threading.Event()
    logs = []
    piper_voice = object()
    installation = SimpleNamespace(
        voices={"af_heart": object()},
        worker_executable=Path("worker.exe"),
        root=Path("kokoro"),
        manifest_sha256="manifest",
        worker_version="worker-version",
        kokoro_version="kokoro-version",
    )

    class Tray(FakeTray):
        def __init__(self, _path, _enqueue):
            self.events = events

        def set_status(self, text):
            if text == "Kokoro is ready":
                ready_status_threads.append(threading.current_thread())
            elif text == "Kokoro unavailable; Piper is ready":
                unavailable_status_threads.append(threading.current_thread())

    class WorkerClient:
        def __init__(self, _config, _voice_id):
            events.append("worker.construct")
            self.process = FakeChildProcess()
            self.shutdown_called = False
            child_processes.append(self.process)
            workers.append(self)

        def ensure_ready(self, cancel_event=None):
            events.append("worker.ready")
            initializer_threads.append(threading.current_thread())
            if failure_stage is None:
                worker_readiness_entered.set()
                assert release_worker_readiness.wait(2)
            if failure_stage == "worker":
                raise RuntimeError("synthetic worker failure")
            if failure_stage == "cancel":
                cancel_event.set()

        def shutdown(self):
            if self.shutdown_called:
                return
            self.shutdown_called = True
            if self.process.running:
                self.process.terminate()
            self.process.wait()
            events.append("worker.shutdown")

    logger = SimpleNamespace(
        warning=lambda *_args: None,
        error=lambda *_args: None,
        exception=lambda *_args: None,
        info=lambda *args: logs.append(args),
    )
    kokoro_settings = replace(
        app.TraySettings(), engine="Kokoro", kokoro_voice="af_heart"
    )

    monkeypatch.setattr(app, "SingleInstance", lambda: instance)
    monkeypatch.setattr(
        app,
        "load_settings",
        lambda: SimpleNamespace(settings=kokoro_settings, source="test"),
    )
    monkeypatch.setattr(app, "configure_logging", lambda _level: logger)
    monkeypatch.setattr(app, "TkUi", lambda: ui)

    show_status = ui.show_status

    def record_failure_message_thread(message):
        if message == "Kokoro is unavailable. Piper will continue to be used.":
            failure_message_threads.append(threading.current_thread())
        show_status(message)

    ui.show_status = record_failure_message_thread

    def make_controller(*args, **kwargs):
        controller = Controller(*args, **kwargs)
        controller.announce_ready = lambda: None
        complete_startup = controller.complete_kokoro_startup
        fail_startup = controller.fail_kokoro_startup

        def record_completion_thread(candidate, voice_ids):
            completion_threads.append(threading.current_thread())
            complete_startup(candidate, voice_ids)

        def record_failure_transition_thread(reason):
            failure_transition_threads.append(threading.current_thread())
            fail_startup(reason)

        controller.complete_kokoro_startup = record_completion_thread
        controller.fail_kokoro_startup = record_failure_transition_thread
        controllers.append(controller)
        return controller

    monkeypatch.setattr(
        app,
        "Controller",
        make_controller,
    )
    monkeypatch.setattr(
        app,
        "_load_configured_voice",
        lambda _settings, _dirs: events.append("voice.load")
        or (Path("voice.onnx"), piper_voice),
    )

    def prepare_kokoro_installation(_logger):
        preparation_threads.append(threading.current_thread())
        events.append("kokoro.prepare")
        if failure_stage == "assets":
            return None, "synthetic asset verification failure"
        return installation, None

    monkeypatch.setattr(
        app,
        "_prepare_kokoro_installation",
        prepare_kokoro_installation,
    )
    monkeypatch.setattr(app, "KokoroWorkerClient", WorkerClient)
    monkeypatch.setattr(app, "TrayIcon", lambda _path, _enqueue: Tray(None, None))
    monkeypatch.setattr(app, "HotkeyManager", lambda: hotkeys)
    monkeypatch.setattr(app, "PowerBroadcastListener", FakePowerListener)
    monkeypatch.setattr(
        app,
        "CodexMonitor",
        lambda *_args, **_kwargs: SimpleNamespace(start=lambda: None, stop=lambda: None),
    )

    def mainloop():
        coordination_threads.append(threading.current_thread())
        if failure_stage is None:
            assert worker_readiness_entered.wait(1)
            assert controllers[0].kokoro_startup_state.name == "LOADING"
            # A scheduled Tk pump still runs while worker readiness is blocked.
            ui.root.callbacks.pop(0)()
            assert controllers[0].kokoro_startup_state.name == "LOADING"
            assert ui.root.callbacks
            release_worker_readiness.set()
        deadline = time.monotonic() + 2
        exit_queued = False
        while ui.root.callbacks and time.monotonic() < deadline:
            ui.root.callbacks.pop(0)()
            if (
                controllers[0].kokoro_startup_state.name in {"READY", "UNAVAILABLE"}
                and not exit_queued
            ):
                controllers[0].enqueue(app.Command(app.CommandKind.EXIT))
                exit_queued = True
            time.sleep(0.002)
        assert controllers[0].kokoro_startup_state.name == (
            "READY" if failure_stage is None else "UNAVAILABLE"
        )

    ui.root.mainloop = mainloop

    assert app.run_app([]) == 0

    assert events.index("voice.load") < events.index("start")
    assert events.index("start") < events.index(("hotkeys.start", "alt+backtick"))
    assert events.index(("hotkeys.start", "alt+backtick")) < events.index(
        "kokoro.prepare"
    )
    if failure_stage != "assets":
        assert events.index("kokoro.prepare") < events.index("worker.ready")
    if failure_stage is None:
        assert controllers[0]._backend_manager.current() is workers[0]
        assert events.index("worker.ready") < events.index("worker.shutdown")
        assert events.index("worker.shutdown") < events.index("hotkeys.stop")
        assert not workers[0].process.running
        assert workers[0].process.terminated
        assert workers[0].process.wait_calls == 1
        assert events.index("process.terminate") < events.index("instance.close")
        assert events.index("process.wait") < events.index("instance.close")
        assert completion_threads == coordination_threads
        assert ready_status_threads == coordination_threads
        assert initializer_threads[0] not in coordination_threads
    else:
        assert controllers[0]._backend_manager.current() is piper_voice
        assert controllers[0].state.settings.engine == "Kokoro"
        assert controllers[0].state.settings.kokoro_voice == "af_heart"
        assert "Kokoro is unavailable. Piper will continue to be used." in ui.statuses
        if failure_stage in {"assets", "worker"}:
            assert failure_transition_threads == coordination_threads
            assert unavailable_status_threads == coordination_threads
            assert failure_message_threads == coordination_threads
            assert preparation_threads
            assert preparation_threads[0] not in coordination_threads
            if failure_stage == "worker":
                assert initializer_threads[0] not in coordination_threads
        if failure_stage == "assets":
            assert "worker.construct" not in events
    if failure_stage != "assets":
        assert events.index("worker.shutdown") < events.index("instance.close")
    logged_messages = [str(value) for item in logs for value in item]
    timing_events = [
        item[0] % item[1:] if len(item) > 1 else item[0]
        for item in logs
        if item and "startup stage=" in str(item[0])
    ]
    expected_stages = [
        "piper_voice_load",
        "tray_hotkey_ready",
        "kokoro_asset_preparation",
    ]
    if failure_stage != "assets":
        expected_stages.append("kokoro_worker_readiness")
    for stage in expected_stages:
        matching_events = [
            message
            for message in timing_events
            if re.fullmatch(
                rf"startup stage={stage} duration_seconds=\d+\.\d{{3}}",
                message,
            )
        ]
        assert len(matching_events) == 1
    if failure_stage == "assets":
        assert not any("kokoro_worker_readiness" in message for message in timing_events)
        assert any("kokoro_asset_preparation" in message for message in logged_messages)
