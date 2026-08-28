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
    def __init__(self, results) -> None:
        self.results = iter(results)
        self.calls = 0
        self.capture_spec = type(
            "Spec",
            (),
            {"canonical": "alt+backtick"},
        )()

    def reregister(self) -> bool:
        self.calls += 1
        return next(self.results)


def test_stale_capture_completion_after_resume_never_starts_speech() -> None:
    speech = FakeSpeech()
    hotkeys = FakeHotkeys([True])
    controller = Controller(
        speech_worker=speech,
        hotkeys=hotkeys,
        capture_submit=lambda _job: None,
    )
    controller.configure_runtime(
        ensure_tray_visible=lambda: None,
    )

    controller.handle(Command(CommandKind.CAPTURE_REQUEST))
    stale = controller.state.capture_generation

    controller.handle(Command(CommandKind.SYSTEM_RESUME))

    controller.handle(
        Command(
            CommandKind.CAPTURE_SUCCEEDED,
            CaptureCompletion(
                stale,
                CaptureResult(
                    CaptureStatus.SUCCESS,
                    "must never be spoken",
                ),
            ),
        )
    )

    assert speech.submitted == []
    assert controller.state.last_text is None


def test_resume_conflict_does_not_prevent_later_clean_exit() -> None:
    speech = FakeSpeech()
    hotkeys = FakeHotkeys([False])
    statuses = []
    teardown = []

    controller = Controller(
        speech_worker=speech,
        hotkeys=hotkeys,
    )
    controller.configure_runtime(
        ensure_tray_visible=lambda: None,
        show_status=statuses.append,
        request_teardown=lambda: teardown.append("run"),
    )

    controller.handle(Command(CommandKind.SYSTEM_RESUME))

    assert controller.state.shutting_down is False
    assert statuses == [
        "That hotkey is already in use. Choose another combination."
    ]

    controller.handle(Command(CommandKind.EXIT))

    assert controller.state.shutting_down is True
    assert teardown == ["run"]


def test_resume_then_new_speech_uses_only_post_resume_generation() -> None:
    speech = FakeSpeech()
    hotkeys = FakeHotkeys([True])

    controller = Controller(
        speech_worker=speech,
        hotkeys=hotkeys,
    )
    controller.configure_runtime(
        ensure_tray_visible=lambda: None,
    )

    controller.state.last_text = "old"
    controller.state.playback = PlaybackState.SPEAKING
    controller.state.speech_generation = 10

    controller.handle(Command(CommandKind.SYSTEM_RESUME))

    assert speech.cancelled == [10]
    assert controller.state.speech_generation == 11

    controller.handle(Command(CommandKind.REPLAY_REQUEST))

    assert speech.submitted[-1].generation == 12
    assert speech.submitted[-1].text == "old"
