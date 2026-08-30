import threading
import logging
import time
from types import SimpleNamespace

import pytest

from piper.windows_tray.speech import (
    SpeechEventKind,
    SpeechPurpose,
    SpeechRequest,
    SpeechWorker,
)


class Chunk:
    def __init__(self, data: bytes) -> None:
        self.audio_int16_bytes = data


class FakePlayer:
    def __init__(self, played: list[bytes], entered: threading.Event) -> None:
        self.played = played
        self.entered = entered
        self.stopped = threading.Event()
        self.play_calls = 0

    def __enter__(self):
        self.entered.set()
        return self

    def __exit__(self, *_args) -> None:
        return None

    def play(self, data: bytes) -> None:
        self.play_calls += 1
        if self.stopped.is_set():
            return
        self.played.append(data)

    def stop(self) -> None:
        self.stopped.set()


class CallbackEvent:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.calls = 0
        self.callback = None
        self.trigger_call = None
        self.forced_false_calls = set()

    def clear(self) -> None:
        self.event.clear()

    def set(self) -> None:
        self.event.set()

    def is_set(self) -> bool:
        self.calls += 1
        if self.callback is not None and self.calls == self.trigger_call:
            callback = self.callback
            self.callback = None
            callback()
        if self.calls in self.forced_false_calls:
            return False
        return self.event.is_set()


def wait_for_event(events: list, kind: SpeechEventKind, generation: int):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        for event in events:
            if event.kind is kind and event.generation == generation:
                return event
        time.sleep(0.01)
    pytest.fail(f"missing {kind.name} event for generation {generation}")


def wait_for_terminal_event(events: list, generation: int):
    deadline = time.monotonic() + 2
    terminal_kinds = {
        SpeechEventKind.FINISHED,
        SpeechEventKind.CANCELLED,
        SpeechEventKind.FAILED,
    }
    while time.monotonic() < deadline:
        for event in events:
            if event.generation == generation and event.kind in terminal_kinds:
                return event
        time.sleep(0.01)
    pytest.fail(f"missing terminal event for generation {generation}")


def make_worker(voice, events, played, entered):
    return SpeechWorker(
        lambda: voice,
        events.append,
        player_factory=lambda _sample_rate: FakePlayer(played, entered),
    )


def test_multi_chunk_request_creates_one_playback_pipeline() -> None:
    events = []
    played = []
    entered = threading.Event()
    factory_calls = []
    voice = SimpleNamespace(
        config=SimpleNamespace(sample_rate=22050),
        synthesize=lambda _text: [Chunk(b"one"), Chunk(b"two")],
    )

    def player_factory(sample_rate):
        factory_calls.append(sample_rate)
        return FakePlayer(played, entered)

    worker = SpeechWorker(lambda: voice, events.append, player_factory)
    try:
        worker.submit(SpeechRequest(301, "hello"))
        wait_for_event(events, SpeechEventKind.FINISHED, 301)
        assert factory_calls == [22050]
        assert played == [b"one", b"two"]
    finally:
        worker.shutdown()


def test_pipeline_exit_failure_is_classified_as_playback_failure() -> None:
    events = []

    class ExitFailingPlayer(FakePlayer):
        def __exit__(self, *_args) -> None:
            raise RuntimeError("ffmpeg exited unexpectedly")

    voice = SimpleNamespace(
        config=SimpleNamespace(sample_rate=22050),
        synthesize=lambda _text: [Chunk(b"audio")],
    )
    worker = SpeechWorker(
        lambda: voice,
        events.append,
        player_factory=lambda _sample_rate: ExitFailingPlayer([], threading.Event()),
    )
    try:
        worker.submit(SpeechRequest(302, "hello"))
        event = wait_for_event(events, SpeechEventKind.FAILED, 302)
        assert event.error == "Speech playback failed."
        assert event.failure_phase == "playback"
    finally:
        worker.shutdown()


def test_stop_induced_broken_pipe_does_not_emit_failed_event() -> None:
    events = []
    write_started = threading.Event()
    release_write = threading.Event()

    class StopBrokenPipePlayer(FakePlayer):
        def play(self, _data: bytes) -> None:
            write_started.set()
            release_write.wait(timeout=2)
            try:
                raise BrokenPipeError("ffplay pipe closed during stop")
            except BrokenPipeError:
                if self.stopped.is_set():
                    return
                raise

        def stop(self) -> None:
            super().stop()
            release_write.set()

    voice = SimpleNamespace(
        config=SimpleNamespace(sample_rate=22050),
        synthesize=lambda _text: [Chunk(b"audio")],
    )
    worker = SpeechWorker(
        lambda: voice,
        events.append,
        player_factory=lambda _sample_rate: StopBrokenPipePlayer([], threading.Event()),
    )
    try:
        worker.submit(SpeechRequest(303, "hello"))
        assert write_started.wait(timeout=1)
        worker.cancel_active(303)
        terminal = wait_for_terminal_event(events, 303)
        assert terminal.kind is SpeechEventKind.CANCELLED
        assert not any(
            event.generation == 303 and event.kind is SpeechEventKind.FAILED
            for event in events
        )
    finally:
        release_write.set()
        worker.shutdown()


def test_speech_worker_emits_started_and_finished_and_plays_audio():
    events = []
    played = []
    entered = threading.Event()
    voice = SimpleNamespace(
        config=SimpleNamespace(sample_rate=22050),
        synthesize=lambda _text: [Chunk(b"audio")],
    )
    worker = make_worker(voice, events, played, entered)

    try:
        worker.submit(SpeechRequest(1, "hello"))
        wait_for_event(events, SpeechEventKind.FINISHED, 1)
        assert [event.kind for event in events] == [
            SpeechEventKind.STARTED,
            SpeechEventKind.FINISHED,
        ]
        assert played == [b"audio"]
        assert entered.is_set()
    finally:
        worker.shutdown()


def test_worker_events_preserve_request_purpose():
    events = []
    played = []
    entered = threading.Event()
    voice = SimpleNamespace(
        config=SimpleNamespace(sample_rate=22050),
        synthesize=lambda _text: [Chunk(b"audio")],
    )
    worker = make_worker(voice, events, played, entered)

    try:
        worker.submit(
            SpeechRequest(100, "error", SpeechPurpose.ERROR)
        )
        terminal = wait_for_event(
            events, SpeechEventKind.FINISHED, 100
        )

        assert events[0].purpose is SpeechPurpose.ERROR
        assert terminal.purpose is SpeechPurpose.ERROR
    finally:
        worker.shutdown()


def test_error_feedback_waits_for_foreground_to_finish():
    events = []
    played = []
    entered = threading.Event()
    release_foreground = threading.Event()

    def synthesize(text):
        if text == "foreground":
            entered.set()
            release_foreground.wait(timeout=2)
        yield Chunk(text.encode())

    voice = SimpleNamespace(
        config=SimpleNamespace(sample_rate=22050),
        synthesize=synthesize,
    )
    worker = make_worker(voice, events, played, entered)

    try:
        worker.submit(
            SpeechRequest(
                101,
                "foreground",
                SpeechPurpose.FOREGROUND,
            )
        )
        assert entered.wait(timeout=1)

        worker.submit(
            SpeechRequest(102, "error", SpeechPurpose.ERROR)
        )
        time.sleep(0.05)
        assert not any(
            event.generation == 102 for event in events
        )

        release_foreground.set()
        wait_for_event(
            events, SpeechEventKind.FINISHED, 102
        )
        assert played == [b"foreground", b"error"]
    finally:
        release_foreground.set()
        worker.shutdown()


def test_error_feedback_runs_before_pending_welcome():
    events = []
    played = []
    entered = threading.Event()
    release = threading.Event()

    def synthesize(text):
        if text == "foreground":
            entered.set()
            release.wait(timeout=2)
        yield Chunk(text.encode())

    voice = SimpleNamespace(
        config=SimpleNamespace(sample_rate=22050),
        synthesize=synthesize,
    )
    worker = make_worker(voice, events, played, entered)

    try:
        worker.submit(
            SpeechRequest(
                103,
                "foreground",
                SpeechPurpose.FOREGROUND,
            )
        )
        assert entered.wait(timeout=1)

        worker.submit(
            SpeechRequest(
                104,
                "welcome",
                SpeechPurpose.WELCOME,
            )
        )
        worker.submit(
            SpeechRequest(105, "error", SpeechPurpose.ERROR)
        )

        release.set()
        wait_for_event(
            events, SpeechEventKind.FINISHED, 104
        )
        assert played == [
            b"foreground",
            b"error",
            b"welcome",
        ]
    finally:
        release.set()
        worker.shutdown()


def test_new_foreground_cancels_active_auxiliary_and_drops_pending_auxiliary():
    events = []
    played = []
    entered = threading.Event()
    release_aux = threading.Event()

    def synthesize(text):
        if text == "active error":
            entered.set()
            release_aux.wait(timeout=2)
        yield Chunk(text.encode())

    voice = SimpleNamespace(
        config=SimpleNamespace(sample_rate=22050),
        synthesize=synthesize,
    )
    worker = make_worker(voice, events, played, entered)

    try:
        worker.submit(
            SpeechRequest(
                106,
                "active error",
                SpeechPurpose.ERROR,
            )
        )
        assert entered.wait(timeout=1)

        worker.submit(
            SpeechRequest(
                107,
                "old welcome",
                SpeechPurpose.WELCOME,
            )
        )
        worker.submit(
            SpeechRequest(
                108,
                "old error",
                SpeechPurpose.ERROR,
            )
        )
        worker.submit(
            SpeechRequest(
                109,
                "fresh selection",
                SpeechPurpose.FOREGROUND,
            )
        )

        release_aux.set()
        wait_for_event(
            events, SpeechEventKind.FINISHED, 109
        )

        assert b"fresh selection" in played
        assert b"old welcome" not in played
        assert b"old error" not in played
    finally:
        release_aux.set()
        worker.shutdown()


def test_foreground_preemption_cancellation_does_not_leak_across_request_handoff():
    events = []
    played = []
    auxiliary_synthesis_started = threading.Event()
    release_auxiliary = threading.Event()
    stop_entered = threading.Event()
    allow_stop_to_return = threading.Event()
    foreground_started = threading.Event()
    submit_done = threading.Event()

    class BlockingStopPlayer(FakePlayer):
        def stop(self) -> None:
            stop_entered.set()
            if not allow_stop_to_return.wait(timeout=2):
                raise RuntimeError("timed out waiting to release auxiliary stop")
            self.stopped.set()

    class WaitingForegroundPlayer(FakePlayer):
        def __enter__(self):
            if not submit_done.wait(timeout=2):
                raise RuntimeError("foreground entered before submit completed")
            return super().__enter__()

    auxiliary_player = BlockingStopPlayer(played, threading.Event())
    foreground_player = WaitingForegroundPlayer(played, threading.Event())
    players = [auxiliary_player, foreground_player]

    def player_factory(_sample_rate):
        return players.pop(0)

    def synthesize(text):
        if text == "auxiliary":
            auxiliary_synthesis_started.set()
            if not release_auxiliary.wait(timeout=2):
                raise RuntimeError("timed out waiting to release auxiliary synthesis")
        yield Chunk(text.encode())

    def on_event(event):
        events.append(event)
        if (
            event.kind is SpeechEventKind.STARTED
            and event.generation == 202
        ):
            foreground_started.set()

    voice = SimpleNamespace(
        config=SimpleNamespace(sample_rate=22050),
        synthesize=synthesize,
    )
    worker = SpeechWorker(
        lambda: voice,
        on_event,
        player_factory=player_factory,
    )

    try:
        worker.submit(
            SpeechRequest(201, "auxiliary", SpeechPurpose.ERROR)
        )
        assert auxiliary_synthesis_started.wait(timeout=1)

        def submit_foreground() -> None:
            worker.submit(
                SpeechRequest(
                    202,
                    "foreground",
                    SpeechPurpose.FOREGROUND,
                )
            )
            submit_done.set()

        submit_thread = threading.Thread(target=submit_foreground)
        submit_thread.start()

        # Current buggy implementation is now blocked in player.stop(),
        # after queuing foreground but before setting the shared cancel event.
        assert stop_entered.wait(timeout=1)

        # Let auxiliary speech finish. The worker can now take foreground,
        # make it active, and clear the reusable cancel event.
        release_auxiliary.set()
        assert foreground_started.wait(timeout=1)

        # Release the stale cancellation only after foreground is active.
        allow_stop_to_return.set()
        submit_thread.join(timeout=1)
        assert not submit_thread.is_alive()
        assert submit_done.is_set()

        terminal = wait_for_terminal_event(events, 202)
        assert terminal.kind is SpeechEventKind.FINISHED
        assert b"foreground" in played
    finally:
        release_auxiliary.set()
        allow_stop_to_return.set()
        worker.shutdown()


def test_cancel_auxiliary_stops_active_and_discards_pending_auxiliary():
    events = []
    played = []
    entered = threading.Event()
    release = threading.Event()

    def synthesize(text):
        if text == "active error":
            entered.set()
            release.wait(timeout=2)
        yield Chunk(text.encode())

    voice = SimpleNamespace(
        config=SimpleNamespace(sample_rate=22050),
        synthesize=synthesize,
    )
    worker = make_worker(voice, events, played, entered)

    try:
        worker.submit(
            SpeechRequest(
                110,
                "active error",
                SpeechPurpose.ERROR,
            )
        )
        assert entered.wait(timeout=1)
        worker.submit(
            SpeechRequest(
                111,
                "pending error",
                SpeechPurpose.ERROR,
            )
        )
        worker.submit(
            SpeechRequest(
                112,
                "pending welcome",
                SpeechPurpose.WELCOME,
            )
        )

        worker.cancel_auxiliary()
        release.set()

        terminal = wait_for_terminal_event(events, 110)
        assert terminal.kind is SpeechEventKind.CANCELLED
        time.sleep(0.05)
        assert not any(
            event.generation in {111, 112}
            for event in events
        )
    finally:
        release.set()
        worker.shutdown()


def test_cancel_active_stops_player_and_discards_later_chunks():
    events = []
    played = []
    entered = threading.Event()
    release = threading.Event()

    def synthesize(_text):
        yield Chunk(b"first")
        release.wait(timeout=2)
        yield Chunk(b"stale")

    voice = SimpleNamespace(
        config=SimpleNamespace(sample_rate=22050), synthesize=synthesize
    )
    worker = make_worker(voice, events, played, entered)

    try:
        worker.submit(SpeechRequest(2, "hello"))
        assert entered.wait(timeout=1)
        worker.cancel_active(2)
        release.set()
        wait_for_event(events, SpeechEventKind.CANCELLED, 2)
        assert played == [b"first"]
        assert not any(event.kind is SpeechEventKind.FINISHED for event in events)
    finally:
        release.set()
        worker.shutdown()


def test_synthesis_failure_emits_generic_failed_event():
    events = []
    played = []
    entered = threading.Event()

    def synthesize(_text):
        raise ValueError("secret selected text")

    voice = SimpleNamespace(
        config=SimpleNamespace(sample_rate=22050), synthesize=synthesize
    )
    worker = make_worker(voice, events, played, entered)

    try:
        worker.submit(SpeechRequest(3, "secret selected text"))
        event = wait_for_event(events, SpeechEventKind.FAILED, 3)
        assert event.error == "Speech synthesis failed."
        assert "secret" not in event.error
        assert event.failure_phase == "synthesis"
    finally:
        worker.shutdown()


def test_playback_failure_emits_generic_failed_event():
    events = []
    entered = threading.Event()

    class FailingPlayer(FakePlayer):
        def play(self, _data: bytes) -> None:
            raise OSError("device details")

    voice = SimpleNamespace(
        config=SimpleNamespace(sample_rate=22050),
        synthesize=lambda _text: [Chunk(b"audio")],
    )
    worker = SpeechWorker(
        lambda: voice,
        events.append,
        player_factory=lambda _sample_rate: FailingPlayer([], entered),
    )

    try:
        worker.submit(SpeechRequest(4, "hello"))
        event = wait_for_event(events, SpeechEventKind.FAILED, 4)
        assert event.error == "Speech playback failed."
        assert "device" not in event.error
    finally:
        worker.shutdown()


def test_player_factory_failure_is_reported_as_playback_failure():
    events = []
    voice = SimpleNamespace(
        config=SimpleNamespace(sample_rate=22050),
        synthesize=lambda _text: [Chunk(b"audio")],
    )

    def player_factory(_sample_rate):
        raise RuntimeError("ffplay unavailable")

    worker = SpeechWorker(lambda: voice, events.append, player_factory)

    try:
        worker.submit(SpeechRequest(41, "hello"))
        event = wait_for_event(events, SpeechEventKind.FAILED, 41)
        assert event.error == "Speech playback failed."
        assert event.failure_phase == "playback"
    finally:
        worker.shutdown()


def test_player_context_entry_failure_is_reported_as_playback_failure():
    events = []
    voice = SimpleNamespace(
        config=SimpleNamespace(sample_rate=22050),
        synthesize=lambda _text: [Chunk(b"audio")],
    )

    class BrokenPlayerContext:
        def __enter__(self):
            raise OSError("audio backend unavailable")

        def __exit__(self, *_args):
            return None

    worker = SpeechWorker(
        lambda: voice,
        events.append,
        player_factory=lambda _sample_rate: BrokenPlayerContext(),
    )

    try:
        worker.submit(SpeechRequest(42, "hello"))
        event = wait_for_event(events, SpeechEventKind.FAILED, 42)
        assert event.error == "Speech playback failed."
        assert event.failure_phase == "playback"
    finally:
        worker.shutdown()


def test_audio_player_broken_pipe_is_reported_as_playback_failure():
    events = []
    entered = threading.Event()

    class BrokenPipePlayer(FakePlayer):
        def play(self, _data: bytes) -> None:
            raise BrokenPipeError("pipe closed")

    voice = SimpleNamespace(
        config=SimpleNamespace(sample_rate=22050),
        synthesize=lambda _text: [Chunk(b"audio")],
    )
    worker = SpeechWorker(
        lambda: voice,
        events.append,
        player_factory=lambda _sample_rate: BrokenPipePlayer([], entered),
    )

    try:
        event = None
        worker.submit(SpeechRequest(40, "hello"))
        event = wait_for_event(events, SpeechEventKind.FAILED, 40)
        assert event.error == "Speech playback failed."
    finally:
        worker.shutdown()


def test_latest_pending_request_replaces_older_pending_request():
    events = []
    played = []
    entered = threading.Event()
    release = threading.Event()
    started = threading.Event()

    def synthesize(text):
        started.set()
        release.wait(timeout=2)
        yield Chunk(text.encode())

    voice = SimpleNamespace(
        config=SimpleNamespace(sample_rate=22050), synthesize=synthesize
    )
    worker = make_worker(voice, events, played, entered)

    try:
        worker.submit(SpeechRequest(5, "first"))
        assert started.wait(timeout=1)
        worker.submit(SpeechRequest(6, "old pending"))
        worker.submit(SpeechRequest(7, "latest"))
        release.set()
        wait_for_event(events, SpeechEventKind.FINISHED, 7)
        assert played == [b"first", b"latest"]
        assert not any(event.generation == 6 for event in events)
    finally:
        release.set()
        worker.shutdown()


def test_cancel_active_discards_matching_pending_request():
    events = []
    played = []
    entered = threading.Event()
    release = threading.Event()

    def synthesize(text):
        if text == "active":
            entered.set()
            release.wait(timeout=2)
        yield Chunk(text.encode())

    voice = SimpleNamespace(
        config=SimpleNamespace(sample_rate=22050), synthesize=synthesize
    )
    worker = make_worker(voice, events, played, entered)

    try:
        worker.submit(SpeechRequest(14, "active"))
        assert entered.wait(timeout=1)
        worker.submit(SpeechRequest(15, "stale pending"))

        worker.cancel_active(15)
        release.set()
        wait_for_event(events, SpeechEventKind.FINISHED, 14)
        time.sleep(0.1)

        assert played == [b"active"]
        assert not any(event.generation == 15 for event in events)
    finally:
        release.set()
        worker.shutdown()


def test_shutdown_stops_active_work_and_joins_worker():
    events = []
    played = []
    entered = threading.Event()
    release = threading.Event()

    def synthesize(_text):
        entered.wait(timeout=2)
        release.wait(timeout=2)
        yield Chunk(b"audio")

    voice = SimpleNamespace(
        config=SimpleNamespace(sample_rate=22050), synthesize=synthesize
    )
    worker = make_worker(voice, events, played, entered)
    worker.submit(SpeechRequest(8, "hello"))
    assert entered.wait(timeout=1)

    worker.shutdown()
    release.set()
    worker.shutdown()

    assert not worker._thread.is_alive()


def test_shutdown_logs_timeout_without_raising(caplog):
    worker = make_worker(
        SimpleNamespace(config=SimpleNamespace(sample_rate=22050), synthesize=lambda _text: []),
        [],
        [],
        threading.Event(),
    )

    class StuckThread:
        name = "piper-speech"

        def join(self, timeout):
            assert timeout == 5

        def is_alive(self):
            return True

    worker._thread = StuckThread()
    speech_logger = logging.getLogger("piper.windows_tray.speech")
    speech_logger.addHandler(caplog.handler)
    previous_level = speech_logger.level
    speech_logger.setLevel(logging.ERROR)
    try:
        worker.shutdown()
    finally:
        speech_logger.removeHandler(caplog.handler)
        speech_logger.setLevel(previous_level)

    assert "speech shutdown timed_out=true thread=piper-speech" in caplog.text


def test_cancellation_at_play_boundary_stops_player_before_chunk_is_played():
    events = []
    played = []
    entered = threading.Event()
    cancel_event = CallbackEvent()
    voice = SimpleNamespace(
        config=SimpleNamespace(sample_rate=22050),
        synthesize=lambda _text: [Chunk(b"stale")],
    )
    worker = make_worker(voice, events, played, entered)
    worker._cancel_event_factory = lambda: cancel_event

    player = worker._player_factory(22050)
    worker._player_factory = lambda _sample_rate: player
    cancel_event.trigger_call = 3
    cancel_event.forced_false_calls.add(3)
    cancel_event.callback = lambda: worker.cancel_active(9)
    try:
        worker.submit(SpeechRequest(9, "hello"))
        wait_for_event(events, SpeechEventKind.CANCELLED, 9)
        assert played == []
        assert player.play_calls == 0
    finally:
        worker.shutdown()


def test_cancellation_before_next_discards_chunk_without_advancing_synthesis():
    events = []
    played = []
    entered = threading.Event()
    cancel_event = CallbackEvent()
    next_calls = []

    class Chunks:
        def __iter__(self):
            return self

        def __next__(self):
            next_calls.append(True)
            return Chunk(b"stale")

    voice = SimpleNamespace(
        config=SimpleNamespace(sample_rate=22050),
        synthesize=lambda _text: Chunks(),
    )
    worker = make_worker(voice, events, played, entered)
    worker._cancel_event_factory = lambda: cancel_event
    cancel_event.trigger_call = 2
    cancel_event.callback = lambda: worker.cancel_active(9)

    try:
        worker.submit(SpeechRequest(9, "hello"))
        wait_for_event(events, SpeechEventKind.CANCELLED, 9)
        assert next_calls == []
        assert played == []
    finally:
        worker.shutdown()


def test_cancellation_during_terminal_selection_emits_cancelled():
    events = []
    played = []
    entered = threading.Event()
    cancel_event = CallbackEvent()
    voice = SimpleNamespace(
        config=SimpleNamespace(sample_rate=22050),
        synthesize=lambda _text: [Chunk(b"audio")],
    )
    worker = make_worker(voice, events, played, entered)
    worker._cancel_event_factory = lambda: cancel_event

    def cancel_at_terminal_check():
        worker.cancel_active(10)

    cancel_event.trigger_call = 4
    cancel_event.forced_false_calls.add(4)
    cancel_event.callback = cancel_at_terminal_check
    try:
        worker.submit(SpeechRequest(10, "hello"))
        wait_for_event(events, SpeechEventKind.CANCELLED, 10)
        assert not any(
            event.kind is SpeechEventKind.FINISHED and event.generation == 10
            for event in events
        )
    finally:
        worker.shutdown()


def test_failure_after_played_chunk_is_reported_as_synthesis_failure():
    events = []
    played = []
    entered = threading.Event()

    def synthesize(_text):
        yield Chunk(b"first")
        raise ValueError("later synthesis failure")

    voice = SimpleNamespace(
        config=SimpleNamespace(sample_rate=22050), synthesize=synthesize
    )
    worker = make_worker(voice, events, played, entered)

    try:
        worker.submit(SpeechRequest(11, "hello"))
        event = wait_for_event(events, SpeechEventKind.FAILED, 11)
        assert event.error == "Speech synthesis failed."
        assert played == [b"first"]
    finally:
        worker.shutdown()


def test_cancel_coordinates_with_blocked_play_boundary_without_deadlock():
    events = []
    entered = threading.Event()
    release_play = threading.Event()
    stop_called = threading.Event()
    cancel_done = threading.Event()

    class BlockingPlayer(FakePlayer):
        def play(self, _data: bytes) -> None:
            self.play_calls += 1
            entered.set()
            release_play.wait(timeout=2)

        def stop(self) -> None:
            stop_called.set()
            self.stopped.set()

    player = BlockingPlayer([], entered)
    voice = SimpleNamespace(
        config=SimpleNamespace(sample_rate=22050),
        synthesize=lambda _text: [Chunk(b"audio")],
    )
    worker = SpeechWorker(
        lambda: voice,
        events.append,
        player_factory=lambda _sample_rate: player,
    )

    try:
        worker.submit(SpeechRequest(12, "hello"))
        assert entered.wait(timeout=1)
        cancel_thread = threading.Thread(
            target=lambda: (worker.cancel_active(12), cancel_done.set())
        )
        cancel_thread.start()
        assert stop_called.wait(timeout=1)
        assert not cancel_done.wait(timeout=0.1)
        release_play.set()
        cancel_thread.join(timeout=1)
        assert cancel_done.is_set()
        terminal = wait_for_terminal_event(events, 12)
        assert terminal.kind in (
            SpeechEventKind.CANCELLED,
            SpeechEventKind.FINISHED,
        )
    finally:
        release_play.set()
        worker.shutdown()


def test_cancel_coordinates_with_terminal_event_emission():
    events = []
    entered = threading.Event()
    release_terminal = threading.Event()
    terminal_started = threading.Event()
    cancel_done = threading.Event()

    def on_event(event):
        events.append(event)
        if event.kind is SpeechEventKind.FINISHED:
            terminal_started.set()
            release_terminal.wait(timeout=2)

    voice = SimpleNamespace(
        config=SimpleNamespace(sample_rate=22050),
        synthesize=lambda _text: [Chunk(b"audio")],
    )
    worker = SpeechWorker(
        lambda: voice,
        on_event,
        player_factory=lambda _sample_rate: FakePlayer([], entered),
    )

    try:
        worker.submit(SpeechRequest(13, "hello"))
        assert terminal_started.wait(timeout=1)
        cancel_thread = threading.Thread(
            target=lambda: (worker.cancel_active(13), cancel_done.set())
        )
        cancel_thread.start()
        assert not cancel_done.wait(timeout=0.1)
        release_terminal.set()
        cancel_thread.join(timeout=1)
        assert cancel_done.is_set()
        assert [event.kind for event in events] == [
            SpeechEventKind.STARTED,
            SpeechEventKind.FINISHED,
        ]
    finally:
        release_terminal.set()
        worker.shutdown()
