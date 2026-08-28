from pathlib import Path
from types import SimpleNamespace

import pytest

from piper.windows_tray.commands import Command, CommandKind
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
        def __init__(self, text, action, enabled=None):
            self.text = text
            self.action = action
            self.enabled = enabled

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

    class FakePystray:
        MenuItem = FakeMenuItem
        Menu = FakeMenu
        Icon = FakeIcon

    monkeypatch.setattr(tray_icon, "_load_dependencies", lambda: (FakePystray, FakeImageApi))

    commands = []
    tray = tray_icon.TrayIcon(tmp_path / "icon.png", commands.append)
    tray.start()
    for item in tray._icon.menu.items:
        item.action(None, item)

    assert [command.kind for command in commands] == [
        CommandKind.CONFIGURE_VOICE,
        CommandKind.SHOW_LAST_TEXT,
        CommandKind.STOP_REQUEST,
        CommandKind.REPLAY_REQUEST,
        CommandKind.CONFIGURE_HOTKEY,
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

    class FakeImageApi:
        @staticmethod
        def open(_path):
            return object()

    class FakePystray:
        Icon = FakeIcon
        Menu = lambda *items: SimpleNamespace(items=items)
        MenuItem = lambda text, action, enabled=None: SimpleNamespace(
            text=text, action=action, enabled=enabled
        )

    monkeypatch.setattr(tray_icon, "_load_dependencies", lambda: (FakePystray, FakeImageApi))
    tray = tray_icon.TrayIcon(tmp_path / "icon.png", lambda _command: None)

    tray.start()
    tray.stop()

    assert calls == ["start", "stop"]


def test_tray_update_menu_delegates_to_pystray(monkeypatch, tmp_path: Path) -> None:
    import piper.windows_tray.tray_icon as tray_icon

    calls = []

    class FakeIcon:
        def __init__(self, *_args, **_kwargs):
            pass

        def run_detached(self):
            pass

        def update_menu(self):
            calls.append("update")

    class FakeImageApi:
        @staticmethod
        def open(_path):
            return object()

    class FakePystray:
        Icon = FakeIcon
        Menu = lambda *items: SimpleNamespace(items=items)
        MenuItem = lambda text, action, enabled=None: SimpleNamespace(
            text=text, action=action, enabled=enabled
        )

    monkeypatch.setattr(tray_icon, "_load_dependencies", lambda: (FakePystray, FakeImageApi))
    tray = tray_icon.TrayIcon(tmp_path / "icon.png", lambda _command: None)

    tray.start()
    tray.update_menu()

    assert calls == ["update"]


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

    def show_last_text(self, _text):
        pass

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

    def ensure_visible(self):
        self.events.append("ensure")


class FakePowerListener:
    last = None

    def __init__(self):
        FakePowerListener.last = self
        self.callback = None
        self.stop_calls = 0

    def start(self, callback):
        self.callback = callback

    def stop(self):
        self.stop_calls += 1


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
    monkeypatch.setattr(
        app,
        "Controller",
        lambda *args, **kwargs: events.append("controller")
        or Controller(*args, **kwargs),
    )
    monkeypatch.setattr(
        app,
        "_load_configured_voice",
        lambda _settings, _dirs: events.append("voice") or (Path("voice.onnx"), object()),
    )
    tray = FakeTray(Path("icon.png"), lambda command: None)
    monkeypatch.setattr(app, "TrayIcon", lambda path, enqueue: events.append("tray") or tray)
    monkeypatch.setattr(app, "PowerBroadcastListener", FakePowerListener)
    return app, instance, ui, tray


def test_power_resume_callback_enqueues_system_resume_and_stops(monkeypatch):
    events = []
    app, _instance, ui, _tray = _patch_primary_app(monkeypatch, events)

    controller_holder = []
    original_controller = app.Controller
    monkeypatch.setattr(
        app,
        "Controller",
        lambda *args, **kwargs: controller_holder.append(
            original_controller(*args, **kwargs)
        )
        or controller_holder[-1],
    )

    ui.root.mainloop = lambda: None
    assert app.run_app([]) == 0

    controller = controller_holder[0]
    power = FakePowerListener.last
    power.callback()
    command = controller.drain_once()

    assert command.kind is CommandKind.SYSTEM_RESUME
    assert power.stop_calls == 1


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
    assert events[-2:] == ["quit", "destroy"]
    assert tray.events == ["start", "stop"]


def test_run_app_debug_forces_debug_logging_and_console(monkeypatch) -> None:
    events = []
    app, _instance, ui, _tray = _patch_primary_app(monkeypatch, events)
    logging_calls = []

    monkeypatch.setattr(
        app,
        "configure_logging",
        lambda level, *args, **kwargs: logging_calls.append(
            (level, args, kwargs)
        )
        or SimpleNamespace(
            warning=lambda *_args: None,
            error=lambda *_args: None,
            exception=lambda *_args: None,
            info=lambda *_args: None,
        ),
    )
    ui.root.mainloop = lambda: None

    assert app.run_app(debug=True) == 0
    assert logging_calls == [("DEBUG", (), {"console": True})]


def test_run_app_without_debug_preserves_settings_logging(monkeypatch) -> None:
    events = []
    app, _instance, ui, _tray = _patch_primary_app(monkeypatch, events)
    logging_calls = []

    monkeypatch.setattr(
        app,
        "configure_logging",
        lambda level, *args, **kwargs: logging_calls.append(
            (level, args, kwargs)
        )
        or SimpleNamespace(
            warning=lambda *_args: None,
            error=lambda *_args: None,
            exception=lambda *_args: None,
            info=lambda *_args: None,
        ),
    )
    ui.root.mainloop = lambda: None

    assert app.run_app() == 0
    assert logging_calls == [("INFO", (), {})]


def test_invalid_persisted_hotkey_recovers_to_default_and_reports_status(monkeypatch):
    events = []
    app, _instance, ui, _tray = _patch_primary_app(monkeypatch, events)
    monkeypatch.setattr(
        app,
        "load_settings",
        lambda: SimpleNamespace(
            settings=app.TraySettings(hotkey="not a hotkey"), source="loaded"
        ),
    )
    class FakeHotkeys:
        def __init__(self):
            self.started_spec = None

        def start(self, spec, **_callbacks):
            self.started_spec = spec.canonical

        def set_failure_callback(self, _callback):
            pass

        def stop(self):
            pass

    hotkeys = FakeHotkeys()
    monkeypatch.setattr(app, "HotkeyManager", lambda: hotkeys)
    ui.root.mainloop = lambda: None

    assert app.run_app([]) == 0
    assert hotkeys.started_spec == "alt+backtick"
    assert ui.statuses == [
        "The saved Piper hotkey was invalid; the default hotkey is being used."
    ]


def test_hotkey_stop_failure_does_not_skip_other_shutdown_cleanup(monkeypatch):
    events = []
    app, _instance, ui, tray = _patch_primary_app(monkeypatch, events)

    class FailingHotkeys:
        def set_failure_callback(self, _callback):
            pass

        def start(self, _spec, **_callbacks):
            pass

        def stop(self):
            raise OSError("stop failed")

    hotkeys = FailingHotkeys()
    monkeypatch.setattr(app, "HotkeyManager", lambda: hotkeys)
    ui.root.mainloop = lambda: None

    assert app.run_app([]) == 0
    assert tray.events == ["start", "stop"]
    assert "instance.close" in events
    assert "destroy" in events


def test_tray_stop_failure_does_not_skip_hotkeys_instance_or_ui_cleanup(monkeypatch):
    events = []
    app, _instance, ui, tray = _patch_primary_app(monkeypatch, events)

    class FailingTray(FakeTray):
        def stop(self):
            self.events.append("stop")
            raise OSError("tray stop failed")

    tray = FailingTray(Path("icon.png"), lambda _command: None)
    monkeypatch.setattr(app, "TrayIcon", lambda _path, _enqueue: tray)

    class RecordingHotkeys:
        def set_failure_callback(self, _callback):
            pass

        def start(self, _spec, **_callbacks):
            pass

        def stop(self):
            events.append("hotkeys.stop")

    monkeypatch.setattr(app, "HotkeyManager", RecordingHotkeys)
    ui.root.mainloop = lambda: None

    assert app.run_app([]) == 0
    assert events.index("hotkeys.stop") < events.index("instance.close")
    assert "destroy" in events
    assert tray.events == ["start", "stop"]


def test_hotkey_start_conflict_keeps_tray_alive_for_recovery(monkeypatch):
    events = []
    app, _instance, ui, tray = _patch_primary_app(monkeypatch, events)
    monkeypatch.setattr(app, "save_settings", lambda _settings: None)

    class ConflictingHotkeys:
        def __init__(self):
            self.start_calls = 0
            self.callbacks = None

        def set_failure_callback(self, _callback):
            pass

        def start(self, spec, **callbacks):
            self.start_calls += 1
            self.callbacks = callbacks
            if self.start_calls == 1:
                raise OSError("hotkey in use")

        def rebind(self, candidate):
            self.start(candidate, **self.callbacks)
            return True

        def stop(self):
            events.append("hotkeys.stop")

    hotkeys = ConflictingHotkeys()
    monkeypatch.setattr(app, "HotkeyManager", lambda: hotkeys)

    controller_holder = []
    original_controller = app.Controller
    monkeypatch.setattr(
        app,
        "Controller",
        lambda *args, **kwargs: controller_holder.append(
            original_controller(*args, **kwargs)
        )
        or controller_holder[-1],
    )

    def mainloop():
        controller = controller_holder[0]
        ui.root.callbacks.pop(0)()
        controller.enqueue(app.Command(app.CommandKind.CONFIGURE_HOTKEY, "ctrl+q"))
        ui.root.callbacks.pop(0)()
        controller.enqueue(app.Command(app.CommandKind.EXIT))
        ui.root.callbacks.pop(0)()

    ui.root.mainloop = mainloop

    assert app.run_app([]) == 0
    assert hotkeys.start_calls == 2
    assert ui.statuses == [
        "That hotkey is already in use. Choose another combination."
    ]
    assert tray.events == ["start", "stop"]
    assert "instance.close" in events


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


def test_acquire_failure_still_closes_instance(monkeypatch) -> None:
    import piper.windows_tray.app as app

    events = []
    instance = FakeInstance(events)
    monkeypatch.setattr(app, "SingleInstance", lambda: instance)
    monkeypatch.setattr(
        instance,
        "acquire",
        lambda: events.append("acquire")
        or (_ for _ in ()).throw(OSError("acquire")),
    )

    with pytest.raises(OSError):
        app.run_app([])

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
        monkeypatch.setattr(
            app,
            "Controller",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("controller")
            ),
        )
    else:
        monkeypatch.setattr(app, "Controller", Controller)

    with pytest.raises((OSError, RuntimeError)):
        app.run_app([])

    expected = ["acquire", "instance.close"]
    if failure_stage == "controller":
        expected.extend(["quit", "destroy"])
    assert events == expected


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
    monkeypatch.setattr(app, "Controller", lambda *args, **kwargs: controller)

    def mainloop():
        controller.enqueue(app.Command(app.CommandKind.ACTIVATE))
        ui.root.callbacks.pop(0)()
        controller.enqueue(app.Command(app.CommandKind.EXIT))
        ui.root.callbacks.pop(0)()

    ui.root.mainloop = mainloop
    assert app.run_app([]) == 0

    assert ui.statuses == ["Piper is already running."]
    assert tray.events == ["start", "stop"]
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
    raw_loader_error = "RAW-VOICE-LOADER-DETAIL"
    monkeypatch.setattr(
        app,
        "load_voice_candidate",
        lambda _reference, _dirs: (_ for _ in ()).throw(OSError(raw_loader_error)),
    )
    saved = []
    monkeypatch.setattr(app, "save_settings", saved.append)

    assert app.run_app([]) == 1
    assert saved == []
    assert ui.statuses == [
        "The selected voice could not be loaded."
    ]
    assert raw_loader_error not in ui.statuses


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
