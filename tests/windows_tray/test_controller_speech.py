from piper.windows_tray.capture import CaptureResult, CaptureStatus
from piper.windows_tray.commands import Command, CommandKind
from piper.windows_tray.controller import (
    CaptureCompletion,
    Controller,
    PlaybackState,
)
from piper.windows_tray.speech import SpeechEvent, SpeechEventKind, SpeechRequest


class FakeSpeechWorker:
    def __init__(self):
        self.submitted = []
        self.cancelled = []
        self.auxiliary_cancel_calls = 0
        self.shutdown_calls = 0

    def submit(self, request):
        self.submitted.append(request)

    def cancel_active(self, generation):
        self.cancelled.append(generation)

    def cancel_auxiliary(self):
        self.auxiliary_cancel_calls += 1

    def shutdown(self):
        self.shutdown_calls += 1


def capture_success(controller, generation, text):
    controller.handle(
        Command(
            CommandKind.CAPTURE_SUCCEEDED,
            CaptureCompletion(generation, CaptureResult(CaptureStatus.SUCCESS, text)),
        )
    )


def capture_failure(controller, generation):
    controller.handle(
        Command(
            CommandKind.CAPTURE_FAILED,
            CaptureCompletion(generation, CaptureResult(CaptureStatus.TIMEOUT)),
        )
    )


def test_capture_during_speech_stops_old_generation_before_new_capture():
    worker = FakeSpeechWorker()
    jobs = []
    controller = Controller(speech_worker=worker, capture_submit=jobs.append)

    controller.handle(Command(CommandKind.CAPTURE_REQUEST))
    capture_success(controller, 1, "first")
    old_generation = controller.state.speech_generation

    controller.handle(Command(CommandKind.CAPTURE_REQUEST))

    assert worker.cancelled == [old_generation]
    assert controller.state.playback is PlaybackState.STOPPED
    assert controller.state.speech_generation == old_generation + 1
    assert controller.state.capture_in_progress is True
    assert len(jobs) == 2


def test_successful_replacement_submits_new_text_and_generation():
    worker = FakeSpeechWorker()
    controller = Controller(speech_worker=worker, capture_submit=lambda _job: None)

    controller.handle(Command(CommandKind.CAPTURE_REQUEST))
    capture_success(controller, 1, "first")
    controller.handle(Command(CommandKind.CAPTURE_REQUEST))
    capture_success(controller, 2, "second")

    assert controller.state.last_text == "second"
    assert controller.state.playback is PlaybackState.SPEAKING
    assert worker.submitted == [SpeechRequest(1, "first"), SpeechRequest(3, "second")]


def test_failed_replacement_leaves_old_text_stopped_without_replay():
    worker = FakeSpeechWorker()
    controller = Controller(speech_worker=worker, capture_submit=lambda _job: None)

    controller.handle(Command(CommandKind.CAPTURE_REQUEST))
    capture_success(controller, 1, "old")
    controller.handle(Command(CommandKind.CAPTURE_REQUEST))
    capture_failure(controller, 2)

    assert controller.state.last_text == "old"
    assert controller.state.playback is PlaybackState.STOPPED
    assert worker.submitted == [SpeechRequest(1, "old")]


def test_stop_and_cancel_are_noops_when_not_speaking():
    worker = FakeSpeechWorker()
    controller = Controller(speech_worker=worker)
    before = controller.state.speech_generation

    controller.handle(Command(CommandKind.CANCEL_REQUEST))
    controller.handle(Command(CommandKind.STOP_REQUEST))

    assert controller.state.speech_generation == before
    assert controller.state.playback is PlaybackState.IDLE
    assert worker.cancelled == []
    assert worker.auxiliary_cancel_calls == 2


def test_replay_resubmits_last_text_without_mutating_it():
    worker = FakeSpeechWorker()
    controller = Controller(speech_worker=worker)
    controller.state.last_text = "saved"

    controller.handle(Command(CommandKind.REPLAY_REQUEST))

    assert controller.state.last_text == "saved"
    assert controller.state.playback is PlaybackState.SPEAKING
    assert worker.submitted == [SpeechRequest(1, "saved")]


def test_replay_is_ignored_while_capture_is_in_progress():
    worker = FakeSpeechWorker()
    controller = Controller(speech_worker=worker, capture_submit=lambda _job: None)
    controller.state.last_text = "saved"

    controller.handle(Command(CommandKind.CAPTURE_REQUEST))
    controller.handle(Command(CommandKind.REPLAY_REQUEST))

    assert controller.state.capture_in_progress is True
    assert controller.state.speech_generation == 0
    assert controller.state.playback is PlaybackState.IDLE
    assert controller.tray_snapshot().can_replay is False
    assert worker.submitted == []


def test_stale_worker_events_do_not_change_current_playback():
    worker = FakeSpeechWorker()
    controller = Controller(speech_worker=worker)
    controller.state.last_text = "saved"
    controller.handle(Command(CommandKind.REPLAY_REQUEST))

    controller.handle(
        Command(
            CommandKind.WORKER_EVENT,
            SpeechEvent(SpeechEventKind.FINISHED, generation=0),
        )
    )

    assert controller.state.playback is PlaybackState.SPEAKING
    assert controller.state.speech_generation == 1


def test_matching_worker_terminal_events_update_state_and_report_failures():
    statuses = []
    worker = FakeSpeechWorker()
    controller = Controller(speech_worker=worker)
    controller.configure_runtime(show_status=statuses.append)
    controller.state.last_text = "saved"
    controller.handle(Command(CommandKind.REPLAY_REQUEST))
    generation = controller.state.speech_generation

    controller.handle(
        Command(
            CommandKind.WORKER_EVENT,
            SpeechEvent(SpeechEventKind.FAILED, generation, "ignored detail"),
        )
    )

    assert controller.state.playback is PlaybackState.STOPPED
    assert statuses == [
        "Audio playback failed. See the Piper log for details."
    ]


def test_synthesis_failure_uses_synthesis_message():
    statuses = []
    controller = Controller()
    controller.configure_runtime(show_status=statuses.append)
    controller.state.speech_generation = 3
    controller.state.playback = PlaybackState.SPEAKING

    controller.handle(
        Command(
            CommandKind.WORKER_EVENT,
            SpeechEvent(
                SpeechEventKind.FAILED,
                3,
                "Speech synthesis failed.",
                "synthesis",
            ),
        )
    )

    assert statuses == [
        "Speech could not be generated. See the Piper log for details."
    ]


def test_playback_failure_uses_playback_message():
    statuses = []
    controller = Controller()
    controller.configure_runtime(show_status=statuses.append)
    controller.state.speech_generation = 3
    controller.state.playback = PlaybackState.SPEAKING

    controller.handle(
        Command(
            CommandKind.WORKER_EVENT,
            SpeechEvent(
                SpeechEventKind.FAILED,
                3,
                "Speech playback failed.",
                "playback",
            ),
        )
    )

    assert statuses == [
        "Audio playback failed. See the Piper log for details."
    ]


def test_worker_callback_only_enqueues_worker_event():
    controller = Controller()

    controller.enqueue_worker_event(SpeechEvent(SpeechEventKind.STARTED, 4))

    command = controller.drain_once()
    assert command == Command(
        CommandKind.WORKER_EVENT, SpeechEvent(SpeechEventKind.STARTED, 4)
    )


def test_exit_cancels_speech_and_requests_teardown():
    worker = FakeSpeechWorker()
    controller = Controller(speech_worker=worker)
    controller.state.last_text = "saved"
    controller.state.playback = PlaybackState.SPEAKING
    controller.state.speech_generation = 4
    teardown_calls = []
    controller.configure_runtime(request_teardown=lambda: teardown_calls.append("teardown"))

    controller.enqueue(Command(CommandKind.EXIT))
    controller.drain_once()
    controller.handle(Command(CommandKind.EXIT))
    controller.handle(Command(CommandKind.REPLAY_REQUEST))

    assert controller.state.playback is PlaybackState.SHUTTING_DOWN
    assert worker.cancelled == [4]
    assert teardown_calls == ["teardown"]
    assert worker.submitted == []
