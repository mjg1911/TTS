from pathlib import Path

import pytest

from piper.windows_tray.capture import CaptureResult, CaptureStatus
from piper.windows_tray.commands import Command, CommandKind
from piper.windows_tray.controller import CaptureCompletion, Controller
from piper.windows_tray.errors import UserError, user_message
from piper.windows_tray.settings import TraySettings
from piper.windows_tray.speech import SpeechPurpose


class FakeHotkeys:
    def __init__(self, result=True, results=None):
        self.result = result
        self.results = list(results) if results is not None else None
        self.candidates = []

    def rebind(self, candidate):
        self.candidates.append(candidate)
        if self.results is not None:
            return self.results.pop(0)
        return self.result


class RecordingSpeechWorker:
    def __init__(self):
        self.submitted = []

    def submit(self, request):
        self.submitted.append(request)


@pytest.mark.parametrize(
    ("requested", "error"),
    [
        ("not-a-hotkey", UserError.HOTKEY_INVALID),
        ("ctrl+q", UserError.HOTKEY_CONFLICT),
    ],
)
def test_runtime_hotkey_errors_use_error_speech(requested, error):
    statuses = []
    worker = RecordingSpeechWorker()
    hotkeys = FakeHotkeys(result=False)
    controller = Controller(
        settings=TraySettings(hotkey="alt+backtick", error_sounds=True),
        save_settings=lambda _settings: None,
        hotkeys=hotkeys,
        speech_worker=worker,
    )
    controller.configure_runtime(show_status=statuses.append)

    assert controller.request_hotkey_change(requested) is False

    assert statuses == [user_message(error)]
    assert len(worker.submitted) == 1
    assert worker.submitted[0].text == user_message(error)
    assert worker.submitted[0].purpose is SpeechPurpose.ERROR


def test_settings_change_only_after_native_rebind_succeeds():
    settings = TraySettings(hotkey="alt+backtick")
    saved = []
    notifications = []
    hotkeys = FakeHotkeys(result=False)
    controller = Controller(settings=settings, save_settings=saved.append)
    controller.configure_runtime(
        hotkeys=hotkeys,
        show_status=notifications.append,
        choose_hotkey=lambda: "ctrl+q",
    )

    controller.handle(Command(CommandKind.CONFIGURE_HOTKEY))

    assert controller.state.settings == settings
    assert saved == []
    assert notifications[-1] == "That hotkey is already in use. Choose another combination."


def test_successful_rebind_persists_canonical_hotkey_after_registration():
    settings = TraySettings(hotkey="alt+backtick")
    saved = []
    hotkeys = FakeHotkeys(result=True)
    controller = Controller(settings=settings, save_settings=saved.append)
    controller.configure_runtime(hotkeys=hotkeys, choose_hotkey=lambda: "Ctrl + Q")

    controller.handle(Command(CommandKind.CONFIGURE_HOTKEY))

    assert controller.state.settings.hotkey == "ctrl+q"
    assert saved == [controller.state.settings]
    assert hotkeys.candidates[0].canonical == "ctrl+q"


def test_failed_save_reports_unrecoverable_failure_when_rollback_rebind_fails():
    settings = TraySettings(hotkey="alt+backtick")
    notifications = []
    errors = []
    hotkeys = FakeHotkeys(results=[True, False])

    def fail_save(_settings):
        raise OSError("disk full")

    controller = Controller(
        settings=settings,
        save_settings=fail_save,
    )
    controller.configure_runtime(
        hotkeys=hotkeys,
        show_status=notifications.append,
        log_error=errors.append,
    )

    assert controller.request_hotkey_change("ctrl+q") is False

    assert controller.state.settings == settings
    assert [candidate.canonical for candidate in hotkeys.candidates] == [
        "ctrl+q",
        "alt+backtick",
    ]
    assert notifications[-1] == (
        "Piper hotkey settings could not be saved, and the previous hotkey "
        "could not be restored."
    )
    assert errors[-1] == "Could not restore the previous Piper hotkey"


def test_generationless_capture_success_is_ignored():
    controller = Controller()
    controller.handle(Command(CommandKind.CAPTURE_REQUEST))

    controller.handle(
        Command(
            CommandKind.CAPTURE_SUCCEEDED,
            CaptureResult(CaptureStatus.SUCCESS, "untrusted"),
        )
    )

    assert controller.state.last_text is None
    assert controller.state.capture_in_progress is True

def test_stale_generation_completion_does_not_clear_current_capture():
    controller = Controller(capture_submit=lambda _job: None)
    controller.handle(Command(CommandKind.CAPTURE_REQUEST))
    controller.handle(
        Command(
            CommandKind.CAPTURE_SUCCEEDED,
            CaptureCompletion(0, CaptureResult(CaptureStatus.SUCCESS, "stale")),
        )
    )

    assert controller.state.last_text is None
    assert controller.state.capture_in_progress is True
