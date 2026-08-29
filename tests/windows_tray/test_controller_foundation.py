from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest

from piper.windows_tray.commands import Command, CommandKind
from piper.windows_tray.controller import Controller, PlaybackState
from piper.windows_tray.speech import SpeechEvent, SpeechEventKind


def test_drain_only_retrieves_exit_command() -> None:
    controller = Controller()
    controller.enqueue(Command(CommandKind.EXIT))

    assert controller.state.shutting_down is False
    assert controller.drain_once() == Command(CommandKind.EXIT)
    assert controller.state.shutting_down is False


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


def test_configure_voice_loads_candidate_synchronously_before_commit() -> None:
    from piper.windows_tray.settings import TraySettings

    old_voice = object()
    new_voice = object()
    controller = Controller(
        settings=TraySettings(voice="old.onnx"), save_settings=lambda _settings: None
    )
    controller.set_voice(Path("old.onnx"), old_voice)
    controller.configure_runtime(
        choose_voice=lambda: Path("new.onnx"),
        load_voice=lambda reference: (Path(reference), new_voice),
    )

    controller.handle(Command(CommandKind.CONFIGURE_VOICE))

    assert controller.state.voice_path == Path("new.onnx")
    assert controller.state.voice is new_voice
    assert controller.state.settings.voice == "new.onnx"


def test_tray_snapshot_waits_for_controller_state_lock() -> None:
    controller = Controller()
    started = threading.Event()
    finished = threading.Event()

    controller._state_lock.acquire()
    try:
        def read_snapshot() -> None:
            started.set()
            controller.tray_snapshot()
            finished.set()

        thread = threading.Thread(target=read_snapshot)
        thread.start()
        assert started.wait(timeout=1)
        time.sleep(0.05)
        assert not finished.is_set()
    finally:
        controller._state_lock.release()
        thread.join(timeout=1)

    assert finished.is_set()


def test_shutdown_invalidates_generation_and_ignores_queued_worker_events() -> None:
    controller = Controller()
    controller.state.last_text = "saved"
    controller.handle(Command(CommandKind.REPLAY_REQUEST))
    generation = controller.state.speech_generation
    controller.enqueue(Command(CommandKind.EXIT))

    controller.handle(controller.drain_once())
    controller.handle(
        Command(
            CommandKind.WORKER_EVENT,
            SpeechEvent(SpeechEventKind.FINISHED, generation),
        )
    )

    assert controller.state.playback is PlaybackState.SHUTTING_DOWN
    assert controller.state.speech_generation > generation


def test_snapshot_can_stop_auxiliary_without_changing_foreground_playback():
    from piper.windows_tray.settings import TraySettings

    controller = Controller(settings=TraySettings())
    controller.state.playback = PlaybackState.IDLE
    controller.state.auxiliary_active_generation = 1

    snapshot = controller.tray_snapshot()

    assert snapshot.can_stop is True
    assert controller.state.playback is PlaybackState.IDLE
