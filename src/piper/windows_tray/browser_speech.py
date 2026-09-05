from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum, auto
from threading import RLock

from .browser_protocol import (
    MAX_BROWSER_QUEUE_BYTES,
    MAX_BROWSER_QUEUE_SENTENCES,
    ResponseEndMessage,
    ResponseStartMessage,
    SentenceMessage,
)
from .speech import SpeechEvent, SpeechEventKind, SpeechPurpose, SpeechRequest


class BrowserMessageOutcome(Enum):
    ACCEPTED = auto()
    DUPLICATE = auto()
    STALE = auto()
    OUT_OF_ORDER = auto()
    OVERFLOW = auto()
    SKIPPED_HIGHER_PRIORITY = auto()
    ENDED = auto()
    IGNORED = auto()


@dataclass(frozen=True)
class BrowserSpeechSnapshot:
    response_id: str | None
    next_sequence: int | None
    queued_sentences: int
    queued_bytes: int
    active: bool
    enabled: bool
    overflowed: bool


@dataclass(frozen=True)
class _QueuedSentence:
    conversation_id: str
    response_id: str
    sequence: int
    text: str

    @property
    def size_bytes(self) -> int:
        return len(self.text.encode("utf-8"))


class BrowserSpeechCoordinator:
    def __init__(
        self,
        submit_speech,
        *,
        max_sentences=MAX_BROWSER_QUEUE_SENTENCES,
        max_bytes=MAX_BROWSER_QUEUE_BYTES,
    ) -> None:
        self._submit_speech = submit_speech
        self._max_sentences = max_sentences
        self._max_bytes = max_bytes
        self._lock = RLock()
        self._queue = deque()
        self._queued_bytes = 0
        self._active = None
        self._active_generation = None
        self._generation = 0
        self._current_response = None
        self._expected_sequence = None
        self._faulted_response = None
        self._overflowed_response = None
        self._overflow_sequence = None
        self._ended_response = None
        self._enabled = False

    def handle_message(self, message) -> BrowserMessageOutcome:
        with self._lock:
            if not self._enabled:
                return BrowserMessageOutcome.IGNORED
            if isinstance(message, ResponseStartMessage):
                return self._start_response_locked(message)
            if isinstance(message, SentenceMessage):
                return self._handle_sentence_locked(message)
            if isinstance(message, ResponseEndMessage):
                return self._end_response_locked(message)
            return BrowserMessageOutcome.IGNORED

    def _start_response_locked(self, message):
        response = (message.conversation_id, message.response_id)
        if response != self._current_response:
            self._clear_pending_locked()
            self._current_response = response
            self._expected_sequence = message.sequence_start
        elif self._ended_response == response:
            return BrowserMessageOutcome.STALE
        elif self._overflowed_response == response:
            if message.sequence_start <= self._overflow_sequence:
                return BrowserMessageOutcome.STALE
            self._clear_pending_locked()
            self._expected_sequence = message.sequence_start
        elif message.sequence_start > self._expected_sequence:
            self._clear_pending_locked()
            self._expected_sequence = message.sequence_start
        self._faulted_response = None
        self._overflowed_response = None
        self._overflow_sequence = None
        self._ended_response = None
        return BrowserMessageOutcome.ACCEPTED

    def _handle_sentence_locked(self, message):
        response = (message.conversation_id, message.response_id)
        if response != self._current_response:
            return BrowserMessageOutcome.STALE
        if response in {
            self._faulted_response,
            self._overflowed_response,
            self._ended_response,
        }:
            return BrowserMessageOutcome.STALE
        if message.sequence < self._expected_sequence:
            return BrowserMessageOutcome.DUPLICATE
        if message.sequence > self._expected_sequence:
            self._clear_pending_locked()
            self._faulted_response = response
            return BrowserMessageOutcome.OUT_OF_ORDER

        self._expected_sequence += 1
        item = _QueuedSentence(
            message.conversation_id,
            message.response_id,
            message.sequence,
            message.text,
        )
        next_count = len(self._queue) + 1
        next_bytes = self._queued_bytes + item.size_bytes
        if next_count > self._max_sentences or next_bytes > self._max_bytes:
            self._clear_pending_locked()
            self._overflowed_response = response
            self._overflow_sequence = self._expected_sequence
            return BrowserMessageOutcome.OVERFLOW

        self._queue.append(item)
        self._queued_bytes = next_bytes
        return self._maybe_submit_locked()

    def _end_response_locked(self, message):
        response = (message.conversation_id, message.response_id)
        if response != self._current_response:
            return BrowserMessageOutcome.STALE
        if response in {
            self._faulted_response,
            self._overflowed_response,
            self._ended_response,
        }:
            return BrowserMessageOutcome.STALE
        self._ended_response = response
        return BrowserMessageOutcome.ENDED

    def _maybe_submit_locked(self):
        if not self._enabled or self._active is not None or not self._queue:
            return BrowserMessageOutcome.ACCEPTED
        item = self._queue.popleft()
        self._queued_bytes -= item.size_bytes
        self._generation += 1
        generation = self._generation
        accepted = self._submit_speech(
            SpeechRequest(generation, item.text, SpeechPurpose.BROWSER)
        )
        if not accepted:
            self._clear_pending_locked()
            return BrowserMessageOutcome.SKIPPED_HIGHER_PRIORITY
        self._active = item
        self._active_generation = generation
        return BrowserMessageOutcome.ACCEPTED

    def handle_speech_event(self, event: SpeechEvent) -> None:
        if event.purpose is not SpeechPurpose.BROWSER:
            return
        if event.kind not in {
            SpeechEventKind.FINISHED,
            SpeechEventKind.CANCELLED,
            SpeechEventKind.FAILED,
        }:
            return
        with self._lock:
            if event.generation != self._active_generation:
                return
            self._active = None
            self._active_generation = None
            self._maybe_submit_locked()

    def interrupt_for_higher_priority(self) -> None:
        with self._lock:
            self._clear_pending_locked()

    def clear_browser_speech(self) -> None:
        with self._lock:
            self._clear_pending_locked()

    def enable(self) -> None:
        with self._lock:
            self._enabled = True

    def disable(self) -> None:
        with self._lock:
            self._enabled = False
            self._clear_pending_locked()
            self._current_response = None
            self._expected_sequence = None
            self._faulted_response = None
            self._overflowed_response = None
            self._overflow_sequence = None
            self._ended_response = None

    def snapshot(self) -> BrowserSpeechSnapshot:
        with self._lock:
            response_id = (
                self._current_response[1]
                if self._current_response is not None
                else None
            )
            return BrowserSpeechSnapshot(
                response_id,
                self._expected_sequence,
                len(self._queue),
                self._queued_bytes,
                self._active is not None,
                self._enabled,
                self._overflowed_response is not None,
            )

    def _clear_pending_locked(self) -> None:
        self._queue.clear()
        self._queued_bytes = 0
