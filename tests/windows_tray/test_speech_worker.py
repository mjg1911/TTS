import threading
import time
from types import SimpleNamespace

import pytest

from piper.windows_tray.speech import (
    SpeechEventKind,
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


def make_worker(voice, events, played, entered):
    return SpeechWorker(
        lambda: voice,
        events.append,
        player_factory=lambda _sample_rate: FakePlayer(played, entered),
    )


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
    worker._cancel_event = cancel_event

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
    worker._cancel_event = cancel_event

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
