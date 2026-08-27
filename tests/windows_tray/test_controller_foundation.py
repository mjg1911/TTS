from pathlib import Path
from types import SimpleNamespace

import pytest

from piper.windows_tray.commands import Command, CommandKind
from piper.windows_tray.controller import Controller


def test_exit_state_changes_only_when_controller_drains_command() -> None:
    controller = Controller()
    controller.enqueue(Command(CommandKind.EXIT))

    assert controller.state.shutting_down is False
    controller.drain_once()
    assert controller.state.shutting_down is True


def test_commands_are_immutable() -> None:
    command = Command(CommandKind.OPEN_LOG, Path("log"))

    with pytest.raises(AttributeError):
        command.kind = CommandKind.EXIT


def test_empty_controller_drain_returns_none() -> None:
    assert Controller().drain_once() is None


def test_hotkey_failure_command_reports_that_hotkeys_are_unavailable() -> None:
    statuses = []
    errors = []
    controller = Controller()
    controller.configure_runtime(show_status=statuses.append, log_error=errors.append)

    controller.handle(Command(CommandKind.HOTKEY_FAILED, "GetMessageW returned -1"))

    assert statuses == ["Piper hotkeys stopped unexpectedly; hotkeys are unavailable."]
    assert errors == ["Piper hotkey message loop stopped: GetMessageW returned -1"]


def test_exit_cleanup_continues_when_tray_stop_fails() -> None:
    events = []
    controller = Controller()
    controller.configure_runtime(
        stop_tray=lambda: (_ for _ in ()).throw(OSError("tray stop failed")),
        close_instance=lambda: events.append("instance.close"),
        quit_root=lambda: events.append("quit"),
        log_error=lambda message: events.append(message),
    )

    controller.handle(Command(CommandKind.EXIT))

    assert events == [
        "Piper cleanup step failed: tray stop failed",
        "instance.close",
        "quit",
    ]


def test_controller_owns_settings_and_active_voice() -> None:
    from piper.windows_tray.settings import TraySettings

    settings = TraySettings()
    controller = Controller(settings=settings)
    voice = object()
    controller.set_voice(Path("voice.onnx"), voice)

    assert controller.state.settings is settings
    assert controller.state.voice_path == Path("voice.onnx")
    assert controller.state.voice is voice


def test_failed_voice_settings_save_retains_known_good_state() -> None:
    from piper.windows_tray.settings import TraySettings

    settings = TraySettings()
    controller = Controller(settings=settings, save_settings=lambda _settings: (_ for _ in ()).throw(OSError("disk")))
    old_voice = object()
    controller.set_voice(Path("old.onnx"), old_voice)
    controller.configure_runtime(
        choose_voice=lambda: Path("new.onnx"),
        load_voice=lambda _path: (Path("new.onnx"), object()),
        show_status=lambda message: statuses.append(message),
        log_error=lambda message: errors.append(message),
    )
    statuses = []
    errors = []

    controller.handle(Command(CommandKind.CONFIGURE_VOICE))

    assert controller.state.settings == settings
    assert controller.state.voice_path == Path("old.onnx")
    assert controller.state.voice is old_voice
    assert statuses and errors
