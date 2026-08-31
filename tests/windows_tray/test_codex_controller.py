from datetime import datetime, timezone

from piper.windows_tray.codex_history import CodexCompletedResponse, CodexResponseId
from piper.windows_tray.commands import Command, CommandKind
from piper.windows_tray.controller import Controller, PlaybackState
from piper.windows_tray.settings import TraySettings
from piper.windows_tray.speech import SpeechPurpose


class FakeMonitor:
    def __init__(self):
        self.start_calls = 0
        self.stop_calls = 0
        self.rebaseline_calls = 0

    def start(self):
        self.start_calls += 1

    def stop(self):
        self.stop_calls += 1

    def rebaseline(self):
        self.rebaseline_calls += 1


class FailingStartMonitor(FakeMonitor):
    def start(self):
        self.start_calls += 1
        raise OSError("monitor start failed")


class FakeWorker:
    def __init__(self):
        self.submitted = []
        self.cancel_codex_calls = 0
        self.cancel_auxiliary_calls = 0

    def submit(self, request):
        self.submitted.append(request)
        return True

    def cancel_codex(self):
        self.cancel_codex_calls += 1

    def cancel_auxiliary(self):
        self.cancel_auxiliary_calls += 1


def response(turn="turn-1", text="Codex answer"):
    return CodexCompletedResponse(
        CodexResponseId("conversation-1", turn),
        datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc),
        text,
    )


def handle_next(controller):
    command = controller.drain_once()
    assert command is not None
    controller.handle(command)


def test_codex_response_preserves_selected_text_state():
    worker = FakeWorker()
    controller = Controller(
        settings=TraySettings(codex_enabled=True), speech_worker=worker
    )
    controller.state.last_text = "selected text"
    controller.enqueue_codex_response(response())
    handle_next(controller)

    assert controller.state.last_text == "selected text"
    assert worker.submitted[-1].text == "Codex answer"
    assert worker.submitted[-1].purpose is SpeechPurpose.CODEX
    assert controller.tray_snapshot().can_replay is True


def test_stale_codex_delivery_is_rejected_after_disable():
    worker = FakeWorker()
    monitor = FakeMonitor()
    controller = Controller(
        settings=TraySettings(codex_enabled=True),
        save_settings=lambda _settings: None,
        speech_worker=worker,
    )
    controller.configure_runtime(codex_monitor=monitor)
    controller.enqueue_codex_response(response())
    queued = controller.drain_once()
    controller.handle(Command(CommandKind.TOGGLE_CODEX))
    controller.handle(queued)

    assert worker.submitted == []
    assert controller.state.settings.codex_enabled is False
    assert monitor.stop_calls == 1


def test_codex_is_skipped_while_foreground_is_speaking():
    worker = FakeWorker()
    controller = Controller(
        settings=TraySettings(codex_enabled=True), speech_worker=worker
    )
    controller.state.playback = PlaybackState.SPEAKING
    controller.enqueue_codex_response(response())
    handle_next(controller)

    assert worker.submitted == []
    assert controller.state.playback is PlaybackState.SPEAKING


def test_capture_request_cancels_only_codex_speech():
    worker = FakeWorker()
    jobs = []
    controller = Controller(
        settings=TraySettings(codex_enabled=True),
        speech_worker=worker,
        capture_submit=jobs.append,
    )
    controller.state.auxiliary_active_purpose = SpeechPurpose.CODEX
    controller.state.auxiliary_active_generation = 4
    controller.handle(Command(CommandKind.CAPTURE_REQUEST))

    assert worker.cancel_codex_calls == 1
    assert worker.cancel_auxiliary_calls == 0
    assert controller.state.auxiliary_active_purpose is None
    assert len(jobs) == 1


def test_enabled_monitor_start_is_gated_and_epoch_tagged():
    monitor = FakeMonitor()
    controller = Controller(settings=TraySettings(codex_enabled=True))
    controller.configure_runtime(codex_monitor=monitor)
    before = controller.codex_monitor_epoch

    assert controller.start_configured_codex_monitoring() is True
    assert monitor.start_calls == 1
    assert controller.codex_monitor_epoch == before + 1


def test_failed_codex_monitor_start_does_not_enable_codex():
    monitor = FailingStartMonitor()
    saved = []
    controller = Controller(
        settings=TraySettings(codex_enabled=False),
        save_settings=saved.append,
    )
    controller.configure_runtime(codex_monitor=monitor)

    controller.handle(Command(CommandKind.TOGGLE_CODEX))

    assert controller.state.settings.codex_enabled is False
    assert saved == []
    assert monitor.start_calls == 1
