from pathlib import Path
from types import SimpleNamespace

import pytest

from piper.windows_tray.commands import CommandKind
from piper.windows_tray.controller import Controller


def test_tray_menu_callbacks_only_enqueue_commands(monkeypatch, tmp_path: Path) -> None:
    import piper.windows_tray.tray_icon as tray_icon

    class FakeImage:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class FakeImageApi:
        @staticmethod
        def open(_path):
            return FakeImage()

    class FakeMenuItem:
        def __init__(self, text, action):
            self.text = text
            self.action = action

    class FakeMenu:
        def __init__(self, *items):
            self.items = items

    class FakeIcon:
        def __init__(self, _name, _image, _title, menu):
            self.menu = menu

        def run_detached(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(tray_icon, "Image", FakeImageApi)
    monkeypatch.setattr(tray_icon.pystray, "MenuItem", FakeMenuItem)
    monkeypatch.setattr(tray_icon.pystray, "Menu", FakeMenu)
    monkeypatch.setattr(tray_icon.pystray, "Icon", FakeIcon)

    commands = []
    tray = tray_icon.TrayIcon(tmp_path / "icon.png", commands.append)
    for item in tray._icon.menu.items:
        item.action(None, item)

    assert [command.kind for command in commands] == [
        CommandKind.CONFIGURE_VOICE,
        CommandKind.OPEN_LOG,
        CommandKind.EXIT,
    ]


def test_tray_start_and_stop_delegate_to_pystray(monkeypatch, tmp_path: Path) -> None:
    import piper.windows_tray.tray_icon as tray_icon

    calls = []

    class FakeIcon:
        def __init__(self, *_args, **_kwargs):
            pass

        def run_detached(self):
            calls.append("start")

        def stop(self):
            calls.append("stop")

    monkeypatch.setattr(tray_icon.Image, "open", lambda _path: object())
    monkeypatch.setattr(tray_icon.pystray, "Icon", FakeIcon)
    tray = tray_icon.TrayIcon(tmp_path / "icon.png", lambda _command: None)

    tray.start()
    tray.stop()

    assert calls == ["start", "stop"]


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

    def choose_voice_model(self):
        return None

    def show_status(self, message):
        self.statuses.append(message)

    def close(self):
        self.root.destroy()


class FakeInstance:
    def __init__(self, events):
        self.events = events

    def acquire(self):
        self.events.append("acquire")
        return self.role

    def close(self):
        self.events.append("instance.close")

    def start_activation_watch(self, callback):
        self.events.append("watch")
        self.activation_callback = callback


class FakeTray:
    def __init__(self, _icon_path, enqueue):
        self.enqueue = enqueue
        self.events = []

    def start(self):
        self.events.append("start")

    def stop(self):
        self.events.append("stop")


def _patch_primary_app(monkeypatch, events):
    import piper.windows_tray.app as app

    instance = FakeInstance(events)
    instance.role = app.InstanceRole.PRIMARY
    monkeypatch.setattr(app, "SingleInstance", lambda: instance)
    monkeypatch.setattr(
        app,
        "load_settings",
        lambda: events.append("settings")
        or SimpleNamespace(settings=app.TraySettings(), source="missing"),
    )
    monkeypatch.setattr(app, "configure_logging", lambda _level: events.append("logging") or SimpleNamespace(
        warning=lambda *_args: None,
        error=lambda *_args: None,
        exception=lambda *_args: None,
    ))
    ui = FakeUi(events)
    monkeypatch.setattr(app, "TkUi", lambda: events.append("ui") or ui)
    monkeypatch.setattr(app, "Controller", lambda: events.append("controller") or Controller())
    monkeypatch.setattr(
        app,
        "_load_configured_voice",
        lambda _settings, _dirs: events.append("voice") or (Path("voice.onnx"), object()),
    )
    tray = FakeTray(Path("icon.png"), lambda command: None)
    monkeypatch.setattr(app, "TrayIcon", lambda path, enqueue: events.append("tray") or tray)
    return app, instance, ui, tray


def test_primary_bootstrap_orders_resources_and_exit_cleanup(monkeypatch) -> None:
    events = []
    app, instance, ui, tray = _patch_primary_app(monkeypatch, events)

    def mainloop():
        events.append("mainloop")
        ui.root.callbacks.pop(0)()

    ui.root.mainloop = mainloop
    result = app.run_app([])

    assert result == 0
    assert events[:8] == [
        "acquire",
        "settings",
        "logging",
        "ui",
        "controller",
        "voice",
        "tray",
        "watch",
    ]
    assert events[-2:] == ["instance.close", "destroy"]
    assert tray.events == ["stop"]


def test_exception_before_existing_cleanup_still_closes_instance(monkeypatch) -> None:
    import piper.windows_tray.app as app

    events = []
    instance = FakeInstance(events)
    instance.role = app.InstanceRole.PRIMARY
    monkeypatch.setattr(app, "SingleInstance", lambda: instance)
    monkeypatch.setattr(app, "load_settings", lambda: (_ for _ in ()).throw(OSError("settings")))

    try:
        app.run_app([])
    except OSError:
        pass
    else:
        raise AssertionError("load_settings failure should propagate")

    assert events == ["acquire", "instance.close"]


@pytest.mark.parametrize("failure_stage", ["logging", "ui", "controller"])
def test_primary_pre_tray_failures_close_instance(monkeypatch, failure_stage) -> None:
    import piper.windows_tray.app as app

    events = []
    instance = FakeInstance(events)
    instance.role = app.InstanceRole.PRIMARY
    monkeypatch.setattr(app, "SingleInstance", lambda: instance)
    monkeypatch.setattr(
        app,
        "load_settings",
        lambda: SimpleNamespace(settings=app.TraySettings(), source="missing"),
    )
    if failure_stage == "logging":
        monkeypatch.setattr(
            app,
            "configure_logging",
            lambda _level: (_ for _ in ()).throw(OSError("logging")),
        )
    else:
        monkeypatch.setattr(app, "configure_logging", lambda _level: SimpleNamespace(exception=lambda *_args: None))
    if failure_stage == "ui":
        monkeypatch.setattr(app, "TkUi", lambda: (_ for _ in ()).throw(RuntimeError("ui")))
    else:
        monkeypatch.setattr(app, "TkUi", lambda: FakeUi(events))
    if failure_stage == "controller":
        monkeypatch.setattr(app, "Controller", lambda: (_ for _ in ()).throw(RuntimeError("controller")))
    else:
        monkeypatch.setattr(app, "Controller", Controller)

    with pytest.raises((OSError, RuntimeError)):
        app.run_app([])

    assert events == ["acquire", "instance.close"]


def test_programming_error_in_voice_setup_is_not_treated_as_first_run(monkeypatch) -> None:
    events = []
    app, _instance, ui, _tray = _patch_primary_app(monkeypatch, events)
    monkeypatch.setattr(
        app,
        "_load_configured_voice",
        lambda _settings, _dirs: (_ for _ in ()).throw(AttributeError("bug")),
    )

    with pytest.raises(AttributeError):
        app.run_app([])

    assert ui.statuses == []


def test_tk_thread_dispatches_activation_and_exit(monkeypatch) -> None:
    events = []
    app, instance, ui, tray = _patch_primary_app(monkeypatch, events)
    controller = Controller()
    monkeypatch.setattr(app, "Controller", lambda: controller)

    def mainloop():
        controller.enqueue(app.Command(app.CommandKind.ACTIVATE))
        ui.root.callbacks.pop(0)()
        controller.enqueue(app.Command(app.CommandKind.EXIT))
        ui.root.callbacks.pop(0)()

    ui.root.mainloop = mainloop
    assert app.run_app([]) == 0

    assert ui.statuses == ["Piper is already running."]
    assert tray.events == ["stop"]
    assert events.count("instance.close") == 1
    assert "quit" in events


def test_failed_voice_candidate_does_not_persist_settings(monkeypatch) -> None:
    events = []
    app, instance, ui, _tray = _patch_primary_app(monkeypatch, events)
    monkeypatch.setattr(
        app,
        "_load_configured_voice",
        lambda _settings, _dirs: (_ for _ in ()).throw(FileNotFoundError("voice")),
    )
    ui.choose_voice_model = lambda: Path("bad.onnx")
    monkeypatch.setattr(
        app,
        "load_voice_candidate",
        lambda _reference, _dirs: (_ for _ in ()).throw(OSError("bad model")),
    )
    saved = []
    monkeypatch.setattr(app, "save_settings", saved.append)

    assert app.run_app([]) == 1
    assert saved == []


def test_successful_first_run_voice_is_persisted_after_load(monkeypatch) -> None:
    events = []
    app, _instance, ui, _tray = _patch_primary_app(monkeypatch, events)
    monkeypatch.setattr(
        app,
        "_load_configured_voice",
        lambda _settings, _dirs: (_ for _ in ()).throw(FileNotFoundError("voice")),
    )
    selected = Path("good.onnx")
    ui.choose_voice_model = lambda: selected
    loaded_path = Path("good.onnx").resolve()
    monkeypatch.setattr(app, "load_voice_candidate", lambda _reference, _dirs: (loaded_path, object()))
    saved = []
    monkeypatch.setattr(app, "save_settings", saved.append)

    assert app.run_app([]) == 0
    assert saved and saved[0].voice == str(loaded_path)


def test_secondary_process_closes_without_loading_or_creating_ui(monkeypatch) -> None:
    import piper.windows_tray.app as app

    calls = []

    class FakeInstance:
        def acquire(self):
            calls.append("acquire")
            return app.InstanceRole.SECONDARY

        def close(self):
            calls.append("close")

    monkeypatch.setattr(app, "SingleInstance", FakeInstance)
    monkeypatch.setattr(
        app,
        "load_settings",
        lambda: calls.append("load_settings"),
    )

    assert app.run_app([]) == 0
    assert calls == ["acquire", "close"]
