from piper.windows_tray.browser_protocol import (
    ResponseEndMessage,
    ResponseStartMessage,
    SentenceMessage,
)
from piper.windows_tray.browser_speech import (
    BrowserMessageOutcome,
    BrowserSpeechCoordinator,
)
from piper.windows_tray.speech import (
    SpeechEvent,
    SpeechEventKind,
    SpeechPurpose,
)


class FakeSubmitter:
    def __init__(self) -> None:
        self.accept = True
        self.requests = []

    def __call__(self, request) -> bool:
        if not self.accept:
            return False
        self.requests.append(request)
        return True


def test_first_sentence_submits_immediately_and_second_waits():
    submitter = FakeSubmitter()
    coordinator = BrowserSpeechCoordinator(submitter)
    coordinator.enable()
    coordinator.handle_message(ResponseStartMessage("conv", "resp", 0))
    coordinator.handle_message(SentenceMessage("conv", "resp", 0, "One."))
    coordinator.handle_message(SentenceMessage("conv", "resp", 1, "Two."))
    assert [request.text for request in submitter.requests] == ["One."]
    first = submitter.requests[0]
    coordinator.handle_speech_event(
        SpeechEvent(
            SpeechEventKind.FINISHED,
            first.generation,
            purpose=SpeechPurpose.BROWSER,
        )
    )
    assert [request.text for request in submitter.requests] == ["One.", "Two."]


def test_duplicate_sequence_is_ignored():
    submitter = FakeSubmitter()
    coordinator = BrowserSpeechCoordinator(submitter)
    coordinator.enable()
    coordinator.handle_message(ResponseStartMessage("conv", "resp", 0))
    assert coordinator.handle_message(SentenceMessage("conv", "resp", 0, "One.")) is BrowserMessageOutcome.ACCEPTED
    assert coordinator.handle_message(SentenceMessage("conv", "resp", 0, "One.")) is BrowserMessageOutcome.DUPLICATE


def test_sequence_gap_faults_current_response_and_clears_pending():
    submitter = FakeSubmitter()
    coordinator = BrowserSpeechCoordinator(submitter)
    coordinator.enable()
    coordinator.handle_message(ResponseStartMessage("conv", "resp", 0))
    coordinator.handle_message(SentenceMessage("conv", "resp", 0, "Act."))
    coordinator.handle_message(SentenceMessage("conv", "resp", 1, "Pending."))
    assert coordinator.handle_message(SentenceMessage("conv", "resp", 3, "Gap.")) is BrowserMessageOutcome.OUT_OF_ORDER
    assert coordinator.snapshot().queued_sentences == 0
    assert coordinator.handle_message(SentenceMessage("conv", "resp", 2, "Ignored.")) is BrowserMessageOutcome.STALE


def test_same_response_reconnect_can_advance_sequence_start():
    submitter = FakeSubmitter()
    coordinator = BrowserSpeechCoordinator(submitter)
    coordinator.enable()
    coordinator.handle_message(ResponseStartMessage("conv", "resp", 0))
    coordinator.handle_message(ResponseStartMessage("conv", "resp", 4))
    assert coordinator.snapshot().next_sequence == 4
    assert coordinator.handle_message(SentenceMessage("conv", "resp", 4, "Five.")) is BrowserMessageOutcome.ACCEPTED


def test_worker_rejection_clears_pending_browser_queue():
    submitter = FakeSubmitter()
    submitter.accept = False
    coordinator = BrowserSpeechCoordinator(submitter)
    coordinator.enable()
    coordinator.handle_message(ResponseStartMessage("conv", "resp", 0))
    outcome = coordinator.handle_message(SentenceMessage("conv", "resp", 0, "Blocked."))
    assert outcome is BrowserMessageOutcome.SKIPPED_HIGHER_PRIORITY
    assert coordinator.snapshot().queued_sentences == 0
    assert coordinator.snapshot().active is False


def test_disabled_coordinator_ignores_messages():
    coordinator = BrowserSpeechCoordinator(FakeSubmitter())
    assert coordinator.handle_message(ResponseStartMessage("conv", "resp", 0)) is BrowserMessageOutcome.IGNORED


def test_sentence_after_response_end_is_stale():
    coordinator = BrowserSpeechCoordinator(FakeSubmitter())
    coordinator.enable()
    coordinator.handle_message(ResponseStartMessage("conv", "resp", 0))
    coordinator.handle_message(SentenceMessage("conv", "resp", 0, "One."))

    assert coordinator.handle_message(ResponseEndMessage("conv", "resp", 1, "complete")) is BrowserMessageOutcome.ENDED
    assert coordinator.handle_message(SentenceMessage("conv", "resp", 1, "Too late.")) is BrowserMessageOutcome.STALE
    assert coordinator.handle_message(ResponseStartMessage("conv", "resp", 1)) is BrowserMessageOutcome.STALE


def test_duplicate_start_does_not_clear_overflow():
    coordinator = BrowserSpeechCoordinator(FakeSubmitter(), max_sentences=1)
    coordinator.enable()
    coordinator.handle_message(ResponseStartMessage("conv", "resp", 0))
    coordinator.handle_message(SentenceMessage("conv", "resp", 0, "One."))
    coordinator.handle_message(SentenceMessage("conv", "resp", 1, "Pending."))
    assert coordinator.handle_message(SentenceMessage("conv", "resp", 2, "Overflow.")) is BrowserMessageOutcome.OVERFLOW
    assert coordinator.handle_message(ResponseStartMessage("conv", "resp", 1)) is BrowserMessageOutcome.STALE


def test_advanced_same_response_reconnect_recovers_overflow():
    coordinator = BrowserSpeechCoordinator(FakeSubmitter(), max_sentences=1)
    coordinator.enable()
    coordinator.handle_message(ResponseStartMessage("conv", "resp", 0))
    coordinator.handle_message(SentenceMessage("conv", "resp", 0, "One."))
    coordinator.handle_message(SentenceMessage("conv", "resp", 1, "Pending."))
    coordinator.handle_message(SentenceMessage("conv", "resp", 2, "Overflow."))
    assert coordinator.handle_message(ResponseStartMessage("conv", "resp", 4)) is BrowserMessageOutcome.ACCEPTED
    assert coordinator.handle_message(SentenceMessage("conv", "resp", 4, "Recovered.")) is BrowserMessageOutcome.ACCEPTED


def test_new_response_keeps_old_active_sentence_but_discards_old_pending():
    submitter = FakeSubmitter()
    coordinator = BrowserSpeechCoordinator(submitter)
    coordinator.enable()
    coordinator.handle_message(ResponseStartMessage("conv", "old", 0))
    coordinator.handle_message(SentenceMessage("conv", "old", 0, "Old active."))
    coordinator.handle_message(SentenceMessage("conv", "old", 1, "Old pending."))
    active_generation = submitter.requests[0].generation

    coordinator.handle_message(ResponseStartMessage("conv", "new", 0))
    coordinator.handle_message(SentenceMessage("conv", "new", 0, "New first."))

    assert [request.text for request in submitter.requests] == ["Old active."]
    assert coordinator.snapshot().queued_sentences == 1

    coordinator.handle_speech_event(SpeechEvent(SpeechEventKind.FINISHED, active_generation, purpose=SpeechPurpose.BROWSER))
    assert [request.text for request in submitter.requests] == ["Old active.", "New first."]


def test_queue_overflow_drops_response_remainder_and_recovers_next_response():
    submitter = FakeSubmitter()
    coordinator = BrowserSpeechCoordinator(submitter, max_sentences=2, max_bytes=1024)
    coordinator.enable()
    coordinator.handle_message(ResponseStartMessage("conv", "overflow", 0))
    coordinator.handle_message(SentenceMessage("conv", "overflow", 0, "Active."))
    coordinator.handle_message(SentenceMessage("conv", "overflow", 1, "Pending one."))
    coordinator.handle_message(SentenceMessage("conv", "overflow", 2, "Pending two."))
    outcome = coordinator.handle_message(SentenceMessage("conv", "overflow", 3, "Overflow."))

    assert outcome is BrowserMessageOutcome.OVERFLOW
    assert coordinator.snapshot().overflowed is True
    assert coordinator.snapshot().queued_sentences == 0
    assert coordinator.handle_message(SentenceMessage("conv", "overflow", 4, "Ignored.")) is BrowserMessageOutcome.STALE

    coordinator.handle_message(ResponseStartMessage("conv", "fresh", 0))
    coordinator.handle_message(SentenceMessage("conv", "fresh", 0, "Fresh."))
    assert coordinator.snapshot().response_id == "fresh"
    assert coordinator.snapshot().overflowed is False


def test_utf8_queue_byte_limit_counts_encoded_bytes():
    coordinator = BrowserSpeechCoordinator(
        FakeSubmitter(), max_sentences=10, max_bytes=4
    )
    coordinator.enable()
    coordinator.handle_message(ResponseStartMessage("conv", "resp", 0))
    coordinator.handle_message(SentenceMessage("conv", "resp", 0, "Act."))

    assert coordinator.handle_message(
        SentenceMessage(
            "conv", "resp", 1, bytes((0xC3, 0xA9, 0xC3, 0xA9)).decode("utf-8")
        )
    ) is BrowserMessageOutcome.ACCEPTED
    assert coordinator.snapshot().queued_bytes == 4
    assert coordinator.handle_message(
        SentenceMessage("conv", "resp", 2, "x")
    ) is BrowserMessageOutcome.OVERFLOW


def test_priority_interruption_clears_pending_but_keeps_active_sentence():
    submitter = FakeSubmitter()
    coordinator = BrowserSpeechCoordinator(submitter)
    coordinator.enable()
    coordinator.handle_message(ResponseStartMessage("conv", "resp", 0))
    coordinator.handle_message(SentenceMessage("conv", "resp", 0, "Active."))
    coordinator.handle_message(SentenceMessage("conv", "resp", 1, "Pending."))

    coordinator.interrupt_for_higher_priority()

    snapshot = coordinator.snapshot()
    assert snapshot.active is True
    assert snapshot.queued_sentences == 0


def test_disable_clears_pending_but_leaves_active_sentence_for_worker_cancel():
    submitter = FakeSubmitter()
    coordinator = BrowserSpeechCoordinator(submitter)
    coordinator.enable()
    coordinator.handle_message(ResponseStartMessage("conv", "resp", 0))
    coordinator.handle_message(SentenceMessage("conv", "resp", 0, "Active."))
    coordinator.handle_message(SentenceMessage("conv", "resp", 1, "Pending."))

    coordinator.disable()

    snapshot = coordinator.snapshot()
    assert snapshot.enabled is False
    assert snapshot.active is True
    assert snapshot.queued_sentences == 0


def test_mismatched_terminal_event_does_not_advance_browser_queue():
    submitter = FakeSubmitter()
    coordinator = BrowserSpeechCoordinator(submitter)
    coordinator.enable()
    coordinator.handle_message(ResponseStartMessage("conv", "resp", 0))
    coordinator.handle_message(SentenceMessage("conv", "resp", 0, "Active."))
    coordinator.handle_message(SentenceMessage("conv", "resp", 1, "Pending."))
    active_generation = submitter.requests[0].generation

    coordinator.handle_speech_event(
        SpeechEvent(
            SpeechEventKind.FINISHED,
            active_generation + 1,
            purpose=SpeechPurpose.BROWSER,
        )
    )

    assert [request.text for request in submitter.requests] == ["Active."]
    assert coordinator.snapshot().active is True
    coordinator.handle_speech_event(
        SpeechEvent(
            SpeechEventKind.CANCELLED,
            active_generation,
            purpose=SpeechPurpose.BROWSER,
        )
    )
    assert [request.text for request in submitter.requests] == [
        "Active.",
        "Pending.",
    ]
