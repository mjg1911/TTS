from pathlib import Path

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
