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
