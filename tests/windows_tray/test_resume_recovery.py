from piper.windows_tray.capture import CaptureResult, CaptureStatus
from piper.windows_tray.commands import Command, CommandKind
from piper.windows_tray.controller import (
    CaptureCompletion,
    Controller,
    PlaybackState,
)


class FakeSpeech:
    def __init__(self) -> None:
        self.cancelled = []
        self.submitted = []

    def cancel_active(self, generation: int) -> None:
        self.cancelled.append(generation)

    def submit(self, request) -> None:
        self.submitted.append(request)


class FakeHotkeys:
    def __init__(self, result=True) -> None:
        self.result = result
        self.reregister_calls = 0
        self.capture_spec = type(
            "Spec",
            (),
            {"canonical": "alt+backtick"},
        )()

    def reregister(self) -> bool:
        self.reregister_calls += 1
        return self.result


def make_controller(hotkey_result=True):
    statuses = []
    tray_calls = []
    speech = FakeSpeech()
    hotkeys = FakeHotkeys(hotkey_result)

    controller = Controller(
        hotkeys=hotkeys,
        speech_worker=speech,
        capture_submit=lambda _job: None,
    )
    controller.configure_runtime(
        show_status=statuses.append,
        ensure_tray_visible=lambda: tray_calls.append("ensure"),
    )

    return controller, speech, hotkeys, tray_calls, statuses


def test_resume_cancels_active_speech_before_restoring_resources() -> None:
    controller, speech, hotkeys, tray_calls, _statuses = make_controller()

    controller.state.playback = PlaybackState.SPEAKING
    controller.state.speech_generation = 8

    controller.handle(Command(CommandKind.SYSTEM_RESUME))

    assert speech.cancelled == [8]
    assert controller.state.speech_generation == 9
    assert controller.state.playback is PlaybackState.STOPPED
    assert tray_calls == ["ensure"]
    assert hotkeys.reregister_calls == 1


def test_resume_while_idle_stays_idle() -> None:
    controller, speech, hotkeys, tray_calls, _statuses = make_controller()

    controller.handle(Command(CommandKind.SYSTEM_RESUME))

    assert speech.cancelled == []
    assert controller.state.playback is PlaybackState.IDLE
    assert tray_calls == ["ensure"]
    assert hotkeys.reregister_calls == 1


def test_resume_invalidates_capture_started_before_suspend() -> None:
    controller, speech, _hotkeys, _tray_calls, _statuses = make_controller()

    controller.handle(Command(CommandKind.CAPTURE_REQUEST))
    stale_generation = controller.state.capture_generation

    assert controller.state.capture_in_progress is True

    controller.handle(Command(CommandKind.SYSTEM_RESUME))

    assert controller.state.capture_in_progress is False
    assert controller.state.capture_generation == stale_generation + 1

    controller.handle(
        Command(
            CommandKind.CAPTURE_SUCCEEDED,
            CaptureCompletion(
                stale_generation,
                CaptureResult(
                    CaptureStatus.SUCCESS,
                    "stale pre-suspend selection",
                ),
            ),
        )
    )

    assert speech.submitted == []


def test_resume_hotkey_conflict_keeps_controller_alive() -> None:
    controller, _speech, hotkeys, tray_calls, statuses = make_controller(
        hotkey_result=False
    )

    controller.handle(Command(CommandKind.SYSTEM_RESUME))

    assert controller.state.shutting_down is False
    assert tray_calls == ["ensure"]
    assert hotkeys.reregister_calls == 1
    assert statuses == [
        "That hotkey is already in use. Choose another combination."
    ]
