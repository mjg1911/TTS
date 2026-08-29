import pytest

from piper.windows_tray.commands import Command, CommandKind
from piper.windows_tray.controller import Controller, PlaybackState
from piper.windows_tray.settings import TraySettings
from piper.windows_tray.speech import (
    SpeechEvent,
    SpeechEventKind,
    SpeechPurpose,
    SpeechRequest,
)


class FakeSpeechWorker:
    def __init__(self):
        self.submitted = []
        self.cancelled = []
        self.auxiliary_cancel_calls = 0

    def submit(self, request):
        self.submitted.append(request)

    def cancel_active(self, generation):
        self.cancelled.append(generation)

    def cancel_auxiliary(self):
        self.auxiliary_cancel_calls += 1


def test_tray_snapshot_exposes_error_sounds_setting() -> None:
    assert Controller().tray_snapshot().error_sounds_enabled is False
    assert (
        Controller(settings=TraySettings(error_sounds=False))
        .tray_snapshot()
        .error_sounds_enabled
        is False
    )
    assert (
        Controller(settings=TraySettings(error_sounds=True))
        .tray_snapshot()
        .error_sounds_enabled
        is True
    )


def test_toggle_error_sounds_saves_before_committing_state() -> None:
    settings = TraySettings(error_sounds=False)
    saved = []
    controller_ref = []

    def save_settings(next_settings: TraySettings) -> None:
        controller = controller_ref[0]
        assert controller.state.settings.error_sounds is False
        saved.append(next_settings)

    controller = Controller(settings=settings, save_settings=save_settings)
    controller_ref.append(controller)

    controller.handle(Command(CommandKind.TOGGLE_ERROR_SOUNDS))

    assert saved == [TraySettings(error_sounds=True)]
    assert controller.state.settings == TraySettings(error_sounds=True)
    assert controller.tray_snapshot().error_sounds_enabled is True


@pytest.mark.parametrize(
    "controller",
    [Controller(), Controller(settings=TraySettings(error_sounds=False))],
)
def test_toggle_error_sounds_reports_unavailable_persistence(controller) -> None:
    statuses = []
    controller.configure_runtime(show_status=statuses.append)

    controller.handle(Command(CommandKind.TOGGLE_ERROR_SOUNDS))

    assert statuses == ["Piper error sound settings could not be saved."]


@pytest.mark.parametrize("failure", [OSError("disk"), ValueError("invalid")])
def test_failed_toggle_error_sounds_save_retains_state_and_checkmark(failure) -> None:
    statuses = []
    errors = []
    settings = TraySettings(error_sounds=False)
    controller = Controller(
        settings=settings,
        save_settings=lambda _settings: (_ for _ in ()).throw(failure),
    )
    controller.configure_runtime(show_status=statuses.append, log_error=errors.append)

    controller.handle(Command(CommandKind.TOGGLE_ERROR_SOUNDS))

    assert controller.state.settings == settings
    assert controller.tray_snapshot().error_sounds_enabled is False
    assert errors == ["Could not save Piper error sound settings: %s" % failure]
    assert statuses == ["Piper error sound settings could not be saved."]


def test_auxiliary_started_does_not_change_foreground_playback_or_last_text():
    worker = FakeSpeechWorker()
    controller = Controller(
        settings=TraySettings(error_sounds=False),
        speech_worker=worker,
    )
    controller.state.last_text = "selected text"
    controller.state.playback = PlaybackState.IDLE

    controller.handle(
        Command(
            CommandKind.WORKER_EVENT,
            SpeechEvent(
                SpeechEventKind.STARTED,
                1,
                purpose=SpeechPurpose.WELCOME,
            ),
        )
    )

    assert controller.state.auxiliary_active is True
    assert controller.state.playback is PlaybackState.IDLE
    assert controller.state.last_text == "selected text"
    assert controller.tray_snapshot().can_replay is True


def test_stale_auxiliary_terminal_event_does_not_clear_newer_request():
    worker = FakeSpeechWorker()
    controller = Controller(
        settings=TraySettings(error_sounds=False),
        speech_worker=worker,
    )

    controller.handle(
        Command(
            CommandKind.WORKER_EVENT,
            SpeechEvent(
                SpeechEventKind.STARTED,
                10,
                purpose=SpeechPurpose.ERROR,
            ),
        )
    )
    controller.handle(
        Command(
            CommandKind.WORKER_EVENT,
            SpeechEvent(
                SpeechEventKind.STARTED,
                11,
                purpose=SpeechPurpose.ERROR,
            ),
        )
    )
    controller.handle(
        Command(
            CommandKind.WORKER_EVENT,
            SpeechEvent(
                SpeechEventKind.CANCELLED,
                10,
                purpose=SpeechPurpose.ERROR,
            ),
        )
    )

    assert controller.state.auxiliary_active_generation == 11


def test_auxiliary_failure_does_not_open_foreground_failure_modal():
    statuses = []
    worker = FakeSpeechWorker()
    controller = Controller(
        settings=TraySettings(error_sounds=False),
        speech_worker=worker,
    )
    controller.configure_runtime(show_status=statuses.append)

    controller.handle(
        Command(
            CommandKind.WORKER_EVENT,
            SpeechEvent(
                SpeechEventKind.FAILED,
                1,
                "Speech playback failed.",
                "playback",
                SpeechPurpose.WELCOME,
            ),
        )
    )

    assert statuses == []
    assert controller.state.playback is PlaybackState.IDLE


def test_stop_cancels_auxiliary_without_marking_idle_foreground_stopped():
    worker = FakeSpeechWorker()
    controller = Controller(
        settings=TraySettings(),
        speech_worker=worker,
    )
    controller.state.last_text = "selected text"
    controller.state.playback = PlaybackState.IDLE
    controller.state.auxiliary_active = True

    controller.handle(Command(CommandKind.STOP_REQUEST))

    assert worker.auxiliary_cancel_calls == 1
    assert controller.state.playback is PlaybackState.IDLE
    assert controller.state.last_text == "selected text"
    assert controller.tray_snapshot().can_replay is True


def test_cancel_request_discards_pending_auxiliary_while_foreground_idle():
    worker = FakeSpeechWorker()
    controller = Controller(
        settings=TraySettings(),
        speech_worker=worker,
    )

    controller.handle(Command(CommandKind.CANCEL_REQUEST))

    assert worker.auxiliary_cancel_calls == 1
    assert controller.state.playback is PlaybackState.IDLE
