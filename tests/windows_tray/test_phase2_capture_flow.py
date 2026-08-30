from pathlib import Path
from types import SimpleNamespace

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
    logger = SimpleNamespace(
        warning=lambda *_args: None,
        error=lambda *_args: None,
        exception=lambda *_args: None,
        info=lambda *_args: None,
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
    monkeypatch.setattr(app, "TrayIcon", lambda _path, _enqueue: tray)
    monkeypatch.setattr(app, "HotkeyManager", lambda: hotkeys)
    monkeypatch.setattr(app, "PowerBroadcastListener", FakePowerListener)

    def mainloop():
        controller = controllers[0]
        hotkeys.failure_callback(OSError("GetMessageW returned 0"))
        ui.root.callbacks.pop(0)()
        controller.enqueue(app.Command(app.CommandKind.EXIT))
        ui.root.callbacks.pop(0)()

    ui.root.mainloop = mainloop

    assert app.run_app([]) == 0
    assert events.index("voice") < events.index(("hotkeys.start", "alt+backtick"))
    assert events.index("hotkeys.stop") < events.index("instance.close")
    assert controllers[0]._log_info == logger.info
    assert controllers[0]._show_notification == tray.show_notification
    assert ui.statuses == [
        "Piper hotkeys stopped unexpectedly; hotkeys are unavailable."
    ]
