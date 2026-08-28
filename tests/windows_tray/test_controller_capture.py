import logging
from types import SimpleNamespace

from piper.windows_tray.capture import CaptureResult, CaptureStatus
from piper.windows_tray.commands import Command, CommandKind
from piper.windows_tray.controller import CaptureCompletion, Controller
from piper.windows_tray.settings import TraySettings


def test_capture_requests_collapse_to_newest_pending_request():
    jobs = []
    controller = Controller(capture_submit=jobs.append)

    controller.handle(Command(CommandKind.CAPTURE_REQUEST))
    controller.handle(Command(CommandKind.CAPTURE_REQUEST))
    controller.handle(Command(CommandKind.CAPTURE_REQUEST))

    assert controller.state.capture_generation == 3
    assert controller.state.capture_in_progress is True
    assert len(jobs) == 1

    jobs[0]()
    stale_completion = controller.drain_once()
    controller.handle(stale_completion)

    assert controller.state.capture_in_progress is True
    assert len(jobs) == 2

    jobs[1]()
    current_completion = controller.drain_once()
    controller.handle(current_completion)
    assert controller.state.capture_in_progress is False


def test_stale_capture_completion_is_ignored():
    controller = Controller()
    controller.handle(Command(CommandKind.CAPTURE_REQUEST))
    controller.handle(
        Command(
            CommandKind.CAPTURE_SUCCEEDED,
            CaptureCompletion(0, CaptureResult(CaptureStatus.SUCCESS, "stale")),
        )
    )

    assert controller.state.last_text is None
    assert controller.state.capture_in_progress is True


def test_failed_new_capture_does_not_replace_last_successful_text():
    controller = Controller()
    controller.handle(Command(CommandKind.CAPTURE_REQUEST))
    controller.handle(
        Command(
            CommandKind.CAPTURE_SUCCEEDED,
            CaptureCompletion(1, CaptureResult(CaptureStatus.SUCCESS, "first")),
        )
    )
    controller.handle(Command(CommandKind.CAPTURE_REQUEST))
    controller.handle(
        Command(
            CommandKind.CAPTURE_FAILED,
            CaptureCompletion(2, CaptureResult(CaptureStatus.TIMEOUT)),
        )
    )

    assert controller.state.last_text == "first"


def test_clipboard_access_failure_has_specific_recoverable_message():
    statuses = []
    controller = Controller(capture_submit=lambda _job: None)
    controller.configure_runtime(show_status=statuses.append)

    controller.handle(Command(CommandKind.CAPTURE_REQUEST))
    generation = controller.state.capture_generation

    controller.handle(
        Command(
            CommandKind.CAPTURE_FAILED,
            CaptureCompletion(
                generation,
                CaptureResult(CaptureStatus.ACCESS_ERROR),
            ),
        )
    )

    assert statuses == [
        "The selected text could not be read from the clipboard."
    ]
    assert controller.state.shutting_down is False


def test_no_text_capture_uses_native_notification_without_visual_status():
    notifications = []
    statuses = []
    controller = Controller(capture_submit=lambda _job: None)
    controller.configure_runtime(
        show_notification=notifications.append,
        show_status=statuses.append,
    )

    controller.handle(Command(CommandKind.CAPTURE_REQUEST))
    generation = controller.state.capture_generation
    controller.handle(
        Command(
            CommandKind.CAPTURE_FAILED,
            CaptureCompletion(generation, CaptureResult(CaptureStatus.EMPTY)),
        )
    )

    assert notifications == ["No text selected"]
    assert statuses == []


def test_native_notification_failure_is_logged_without_fallback(caplog):
    statuses = []
    controller = Controller(capture_submit=lambda _job: None)
    controller.configure_runtime(
        show_notification=lambda _message: (_ for _ in ()).throw(
            OSError("native notification failed")
        ),
        show_status=statuses.append,
    )

    with caplog.at_level(logging.ERROR):
        controller.handle(Command(CommandKind.CAPTURE_REQUEST))
        generation = controller.state.capture_generation
        controller.handle(
            Command(
                CommandKind.CAPTURE_FAILED,
                CaptureCompletion(generation, CaptureResult(CaptureStatus.EMPTY)),
            )
        )

    assert "Piper tray notification could not be shown: native notification failed" in caplog.text
    assert statuses == []


def test_cancel_request_is_noop_without_speech():
    controller = Controller()
    before = controller.state.capture_generation

    controller.handle(Command(CommandKind.CANCEL_REQUEST))

    assert controller.state.capture_generation == before


def test_invalid_hotkey_does_not_show_user_input_or_exception_text():
    statuses = []

    class FakeHotkeys:
        def rebind(self, _candidate):
            raise AssertionError("invalid hotkey must be rejected before rebind")

    controller = Controller(
        settings=TraySettings(hotkey="alt+backtick"),
        save_settings=lambda _settings: None,
        hotkeys=FakeHotkeys(),
    )
    controller.configure_runtime(show_status=statuses.append)
    malicious_input = "unsupported key: <SCRIPT>selected text</SCRIPT>"

    assert controller.request_hotkey_change(malicious_input) is False

    assert statuses == ["That hotkey is not valid. Choose another combination."]
    assert malicious_input not in statuses


def test_capture_worker_logs_outcome_and_length_without_text(caplog):
    jobs = []
    result = CaptureResult(CaptureStatus.SUCCESS, "secret")
    controller = Controller(capture=lambda: result, capture_submit=jobs.append)

    with caplog.at_level(logging.INFO):
        controller.handle(Command(CommandKind.CAPTURE_REQUEST))
        jobs[0]()

    assert "capture outcome=SUCCESS length=6" in caplog.text
    assert "secret" not in caplog.text


def test_capture_worker_logs_access_error_without_detail(caplog):
    jobs = []
    result = CaptureResult(CaptureStatus.ACCESS_ERROR, detail="SendInput failed")
    controller = Controller(capture=lambda: result, capture_submit=jobs.append)

    with caplog.at_level(logging.INFO):
        controller.handle(Command(CommandKind.CAPTURE_REQUEST))
        jobs[0]()

    assert "capture outcome=ACCESS_ERROR length=0" in caplog.text
    assert "SendInput failed" not in caplog.text


def test_capture_worker_logs_safe_diagnostics_for_unexpected_exception(caplog):
    jobs = []
    secret = "SELECTED-TEXT-MUST-NOT-LOG"

    def capture():
        raise RuntimeError(secret)

    controller = Controller(capture=capture, capture_submit=jobs.append)

    with caplog.at_level(logging.ERROR):
        controller.handle(Command(CommandKind.CAPTURE_REQUEST))
        jobs[0]()

    assert "capture failed" in caplog.text
    assert "stage=capture_worker" in caplog.text
    assert "exception_type=RuntimeError" in caplog.text
    assert "traceback=controller.py:" in caplog.text
    assert secret not in caplog.text


def test_show_last_text_uses_main_thread_ui_callback():
    shown = []
    controller = Controller()
    controller.configure_runtime(show_last_text=shown.append)
    controller.state.last_text = "selected"

    controller.handle(Command(CommandKind.SHOW_LAST_TEXT))

    assert shown == ["selected"]


def test_show_last_text_ui_has_exact_empty_message(monkeypatch):
    import piper.windows_tray.ui as ui

    calls = []
    monkeypatch.setattr(
        ui.messagebox,
        "showinfo",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    instance = ui.TkUi.__new__(ui.TkUi)
    instance.root = SimpleNamespace()
    instance._thread_id = __import__("threading").get_ident()

    instance.show_last_text(None)

    assert calls == [
        (
            ("Last captured text", "No text has been captured yet."),
            {"parent": instance.root},
        )
    ]
