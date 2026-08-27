from pathlib import Path
from types import SimpleNamespace

from piper.windows_tray.capture import CaptureResult, CaptureStatus
from piper.windows_tray.commands import CommandKind
from piper.windows_tray.controller import Controller


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


class FakeHotkeys:
    def __init__(self, events):
        self.events = events
        self.callbacks = None

    def start(self, spec, on_capture, on_cancel):
        self.events.append(("hotkeys.start", spec.canonical))
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


def test_app_starts_hotkeys_after_voice_setup_and_stops_before_mutex_release(monkeypatch):
    import piper.windows_tray.app as app

    events = []
    instance = FakeInstance(events)
    instance.role = app.InstanceRole.PRIMARY
    ui = FakeUi(events)
    tray = FakeTray(Path("icon.png"), lambda _command: None)
    hotkeys = FakeHotkeys(events)
    controllers = []

    monkeypatch.setattr(app, "SingleInstance", lambda: instance)
    monkeypatch.setattr(
        app,
        "load_settings",
        lambda: SimpleNamespace(settings=app.TraySettings(), source="missing"),
    )
    monkeypatch.setattr(
        app,
        "configure_logging",
        lambda _level: SimpleNamespace(
            warning=lambda *_args: None,
            error=lambda *_args: None,
            exception=lambda *_args: None,
        ),
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

    def mainloop():
        controller = controllers[0]
        controller.enqueue(app.Command(app.CommandKind.EXIT))
        ui.root.callbacks.pop(0)()

    ui.root.mainloop = mainloop

    assert app.run_app([]) == 0
    assert events.index("voice") < events.index(("hotkeys.start", "alt+backtick"))
    assert events.index("hotkeys.stop") < events.index("instance.close")
