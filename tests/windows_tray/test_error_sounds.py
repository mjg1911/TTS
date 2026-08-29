import pytest

from piper.windows_tray.commands import Command, CommandKind
from piper.windows_tray.controller import Controller, PlaybackState
from piper.windows_tray.errors import UserError, user_message
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


def configured_controller(settings):
    worker = FakeSpeechWorker()
    statuses = []
    notifications = []
    errors = []
    shown_last_text = []
    controller = Controller(settings=settings, speech_worker=worker)
    controller.configure_runtime(
        show_status=statuses.append,
        show_notification=notifications.append,
        log_error=errors.append,
        show_last_text=shown_last_text.append,
    )
    return controller, worker, statuses, notifications, errors, shown_last_text


@pytest.mark.parametrize(
    "error",
    [UserError.HOTKEY_CONFLICT, UserError.HOTKEY_INVALID, UserError.CLIPBOARD],
)
@pytest.mark.parametrize("enabled", [True, False])
def test_runtime_error_reports_status_and_conditionally_speaks(error, enabled):
    controller, worker, statuses, notifications, _errors, _shown_last_text = configured_controller(
        TraySettings(error_sounds=enabled)
    )

    controller._report_runtime_error(error)

    assert statuses == [user_message(error)]
    assert notifications == []
    expected = (
        [SpeechRequest(1, user_message(error), SpeechPurpose.ERROR)]
        if enabled
        else []
    )
    assert worker.submitted == expected


def test_no_text_uses_native_notification_and_speaks_full_message():
    controller, worker, statuses, notifications, _errors, _shown_last_text = configured_controller(
        TraySettings(error_sounds=True)
    )

    controller._report_runtime_error(UserError.NO_TEXT)

    assert notifications == ["No text selected"]
    assert statuses == []
    assert worker.submitted == [
        SpeechRequest(1, user_message(UserError.NO_TEXT), SpeechPurpose.ERROR)
    ]


def test_runtime_error_preserves_foreground_state_and_show_last_text():
    controller, _worker, statuses, notifications, _errors, shown_last_text = configured_controller(
        TraySettings(error_sounds=True)
    )
    controller.state.last_text = "selected text"
    controller.state.playback = PlaybackState.SPEAKING
    before = controller.tray_snapshot()

    controller._report_runtime_error(UserError.CLIPBOARD)
    controller.handle(Command(CommandKind.SHOW_LAST_TEXT))

    assert statuses == [user_message(UserError.CLIPBOARD)]
    assert notifications == []
    assert controller.state.last_text == "selected text"
    assert controller.state.playback is PlaybackState.SPEAKING
    assert controller.tray_snapshot().can_replay is before.can_replay
    assert controller.tray_snapshot().has_last_text is before.has_last_text
    assert shown_last_text == ["selected text"]


def test_notification_failure_is_logged_without_modal_fallback_and_still_speaks():
    controller, worker, statuses, _notifications, errors, _shown_last_text = configured_controller(
        TraySettings(error_sounds=True)
    )
    controller.configure_runtime(
        show_notification=lambda _message: (_ for _ in ()).throw(
            RuntimeError("toast unavailable")
        )
    )

    controller._report_runtime_error(UserError.NO_TEXT)

    assert errors == [
        "Piper tray notification could not be shown: toast unavailable"
    ]
    assert statuses == []
    assert worker.submitted == [
        SpeechRequest(1, user_message(UserError.NO_TEXT), SpeechPurpose.ERROR)
    ]


def test_auxiliary_error_speech_failure_is_best_effort_without_feedback():
    controller, worker, statuses, notifications, _errors, _shown_last_text = configured_controller(
        TraySettings(error_sounds=True)
    )
    controller._report_runtime_error(UserError.CLIPBOARD)

    controller.handle(
        Command(
            CommandKind.WORKER_EVENT,
            SpeechEvent(
                SpeechEventKind.FAILED,
                1,
                "Speech synthesis failed.",
                "synthesis",
                SpeechPurpose.ERROR,
            ),
        )
    )

    assert len(worker.submitted) == 1
    assert statuses == [user_message(UserError.CLIPBOARD)]
    assert notifications == []


def test_runtime_error_rejects_unapproved_errors():
    controller, worker, statuses, notifications, _errors, _shown_last_text = configured_controller(
        TraySettings(error_sounds=True)
    )

    with pytest.raises(ValueError):
        controller._report_runtime_error(UserError.PLAYBACK)

    assert worker.submitted == []
    assert statuses == []
    assert notifications == []


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


def test_disabled_error_sounds_submits_welcome_as_auxiliary_only():
    worker = FakeSpeechWorker()
    controller = Controller(
        settings=TraySettings(error_sounds=False),
        speech_worker=worker,
    )
    controller.state.last_text = "selected text"
    controller.state.playback = PlaybackState.IDLE

    controller.announce_ready()

    assert worker.submitted == [
        SpeechRequest(
            1,
            "Piper is ready.",
            SpeechPurpose.WELCOME,
        )
    ]
    assert controller.state.last_text == "selected text"
    assert controller.state.playback is PlaybackState.IDLE
    assert controller.tray_snapshot().can_replay is True


def test_enabled_error_sounds_suppresses_launch_welcome():
    worker = FakeSpeechWorker()
    controller = Controller(
        settings=TraySettings(error_sounds=True),
        speech_worker=worker,
    )

    controller.announce_ready()

    assert worker.submitted == []


def test_welcome_failure_is_best_effort_and_does_not_open_modal():
    statuses = []
    worker = FakeSpeechWorker()
    controller = Controller(
        settings=TraySettings(error_sounds=False),
        speech_worker=worker,
    )
    controller.configure_runtime(show_status=statuses.append)

    controller.announce_ready()
    assert len(worker.submitted) == 1

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

    assert len(worker.submitted) == 1
    assert statuses == []
    assert controller.state.playback is PlaybackState.IDLE


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
