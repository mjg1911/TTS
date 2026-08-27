import logging
from types import SimpleNamespace

from piper.windows_tray.capture import CaptureResult, CaptureStatus
from piper.windows_tray.commands import Command, CommandKind
from piper.windows_tray.controller import CaptureCompletion, Controller


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


def test_cancel_request_is_noop_without_speech():
    controller = Controller()
    before = controller.state.capture_generation

    controller.handle(Command(CommandKind.CANCEL_REQUEST))

    assert controller.state.capture_generation == before


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
