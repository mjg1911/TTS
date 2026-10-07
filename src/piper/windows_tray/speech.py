"""Background speech synthesis and playback coordination for the tray app."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import Enum, auto
import logging
from queue import Empty, Full, Queue
import threading
import time
from typing import Optional

from piper.audio_playback import AudioPlayer

from .logging_setup import log_exception_safe, log_synthesis_result
from .pitch_playback import PlaybackPipeline
from .sentence_splitter import split_speech_sentences
from .settings import DEFAULT_SENTENCE_PAUSE_MS


_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class _SentenceAudio:
    pcm: bytes
    owns_lookahead_slot: bool


@dataclass(frozen=True)
class _SentenceFailure:
    error: Exception


_END_OF_SENTENCES = object()


class _ProducerCancelView:
    """Expose request cancellation and stream shutdown to backend iterators."""

    def __init__(self, request_cancel: threading.Event, producer_stop: threading.Event):
        self._request_cancel = request_cancel
        self._producer_stop = producer_stop

    def is_set(self) -> bool:
        return self._request_cancel.is_set() or self._producer_stop.is_set()


class _BackendSentenceStream(Iterator[bytes]):
    """Synthesize non-Piper sentences ahead of the playback consumer."""

    _WAIT_SECONDS = 0.05

    def __init__(self, backend, text: str, cancel_event: threading.Event) -> None:
        self._backend = backend
        self._sentences = split_speech_sentences(text) or (text,)
        self._request_cancel = cancel_event
        self._stop_event = threading.Event()
        self._backend_cancel = _ProducerCancelView(cancel_event, self._stop_event)
        self._queue: Queue[object] = Queue(maxsize=1)
        self._lookahead_slot = threading.Semaphore(1)
        self._first_sentence_consumed = threading.Event()
        self._timing_lock = threading.Lock()
        self._synthesis_seconds = 0.0
        self._active_iterator = None
        self._started = False
        self._closed = False

        started_at = time.monotonic()
        try:
            self._first_result = backend.synthesize(
                self._sentences[0], self._backend_cancel
            )
        finally:
            self._add_synthesis_time(time.monotonic() - started_at)
        self.sample_rate = self._first_result.sample_rate
        self._producer = threading.Thread(
            target=self._produce,
            name="piper-sentence-producer",
            daemon=True,
        )

    @property
    def synthesis_seconds(self) -> float:
        with self._timing_lock:
            return self._synthesis_seconds

    def _add_synthesis_time(self, seconds: float) -> None:
        with self._timing_lock:
            self._synthesis_seconds += seconds

    def start(self) -> None:
        if self._started:
            return
        self._producer.start()
        self._started = True

    def __iter__(self) -> _BackendSentenceStream:
        return self

    def __next__(self) -> bytes:
        if not self._started:
            raise RuntimeError("sentence stream has not been started")
        while not self._stop_event.is_set() and not self._request_cancel.is_set():
            try:
                item = self._queue.get(timeout=self._WAIT_SECONDS)
            except Empty:
                continue
            if item is _END_OF_SENTENCES:
                raise StopIteration
            if isinstance(item, _SentenceFailure):
                raise item.error
            if not isinstance(item, _SentenceAudio):
                raise RuntimeError("invalid sentence stream item")
            if item.owns_lookahead_slot:
                self._lookahead_slot.release()
            else:
                self._first_sentence_consumed.set()
            return item.pcm
        raise StopIteration

    def _is_active(self) -> bool:
        return not self._stop_event.is_set() and not self._request_cancel.is_set()

    def _reserve_lookahead_slot(self) -> bool:
        while self._is_active():
            if self._lookahead_slot.acquire(timeout=self._WAIT_SECONDS):
                return True
        return False

    def _wait_for_first_sentence(self) -> bool:
        while self._is_active():
            if self._first_sentence_consumed.wait(self._WAIT_SECONDS):
                return True
        return False

    def _put_while_active(self, item: object) -> bool:
        while self._is_active():
            try:
                self._queue.put(item, timeout=self._WAIT_SECONDS)
                return True
            except Full:
                continue
        return False

    @staticmethod
    def _close_iterator(iterator) -> None:
        close = getattr(iterator, "close", None)
        if callable(close):
            close()

    def _collect_audio(self, result) -> bytes:
        iterator = iter(result.chunks)
        self._active_iterator = iterator
        audio = bytearray()
        try:
            while self._is_active():
                try:
                    chunk = next(iterator)
                except StopIteration:
                    break
                if not self._is_active():
                    break
                audio.extend(chunk)
            return bytes(audio)
        finally:
            self._active_iterator = None
            self._close_iterator(iterator)

    def _release_unqueued_slot(self, owns_slot: bool) -> bool:
        if owns_slot:
            self._lookahead_slot.release()
        return False

    def _produce(self) -> None:
        owns_slot = False
        failure = None
        try:
            first_started_at = time.monotonic()
            try:
                first_audio = self._collect_audio(self._first_result)
            finally:
                self._add_synthesis_time(time.monotonic() - first_started_at)
            if first_audio and self._is_active():
                if not self._put_while_active(_SentenceAudio(first_audio, False)):
                    return
            else:
                self._first_sentence_consumed.set()

            for sentence in self._sentences[1:]:
                if not self._wait_for_first_sentence():
                    break
                if not self._reserve_lookahead_slot():
                    break
                owns_slot = True
                if not self._is_active():
                    break
                started_at = time.monotonic()
                try:
                    result = self._backend.synthesize(sentence, self._backend_cancel)
                    if result.sample_rate != self.sample_rate:
                        iterator = iter(result.chunks)
                        try:
                            self._close_iterator(iterator)
                        except Exception:
                            pass
                        raise RuntimeError(
                            "Speech backend changed sample rate during one request"
                        )
                    sentence_audio = self._collect_audio(result)
                finally:
                    self._add_synthesis_time(time.monotonic() - started_at)

                if not self._is_active():
                    break
                if not sentence_audio:
                    owns_slot = self._release_unqueued_slot(owns_slot)
                    continue
                if self._put_while_active(_SentenceAudio(sentence_audio, True)):
                    owns_slot = False
                else:
                    break
        except Exception as caught:
            failure = caught
        finally:
            if owns_slot:
                self._lookahead_slot.release()
            active_iterator = self._active_iterator
            if active_iterator is not None:
                try:
                    self._close_iterator(active_iterator)
                except Exception as caught:
                    if failure is None:
                        failure = caught

            if failure is not None and self._is_active():
                self._put_while_active(_SentenceFailure(failure))
            elif self._is_active():
                self._put_while_active(_END_OF_SENTENCES)

    def _discard_queued_audio(self) -> None:
        while True:
            try:
                item = self._queue.get_nowait()
            except Empty:
                return
            if isinstance(item, _SentenceAudio) and item.owns_lookahead_slot:
                self._lookahead_slot.release()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop_event.set()
        if self._started:
            self._producer.join()
        else:
            self._close_iterator(iter(self._first_result.chunks))
        self._discard_queued_audio()


class SpeechEventKind(Enum):
    STARTED = auto()
    FINISHED = auto()
    CANCELLED = auto()
    FAILED = auto()


class SpeechPurpose(Enum):
    FOREGROUND = auto()
    ERROR = auto()
    BROWSER = auto()
    CODEX = auto()
    WELCOME = auto()
    STARTUP_STATUS = auto()


@dataclass(frozen=True)
class SpeechRequest:
    generation: int
    text: str
    purpose: SpeechPurpose = SpeechPurpose.FOREGROUND
    backend_override: object | None = None


@dataclass(frozen=True)
class SpeechEvent:
    kind: SpeechEventKind
    generation: int
    error: str | None = None
    failure_phase: str | None = None
    purpose: SpeechPurpose = SpeechPurpose.FOREGROUND


class SpeechWorker:
    """Run synthesis and playback away from the tray controller thread."""

    def __init__(
        self,
        voice_provider: Callable[[], object],
        on_event: Callable[[SpeechEvent], None],
        player_factory: Callable[[int], PlaybackPipeline] = AudioPlayer,
    ) -> None:
        self._voice_provider = voice_provider
        self._on_event = on_event
        self._player_factory = player_factory
        self._sentence_pause_provider: Callable[[], int] = (
            lambda: DEFAULT_SENTENCE_PAUSE_MS
        )
        self._piper_sentence_streaming_provider: Callable[[], bool] = lambda: True
        self._condition = threading.Condition()
        self._pending_foreground: Optional[SpeechRequest] = None
        self._pending_errors = deque()  # type: deque[SpeechRequest]
        self._pending_browser: Optional[SpeechRequest] = None
        self._pending_codex: Optional[SpeechRequest] = None
        self._pending_welcome: Optional[SpeechRequest] = None
        self._pending_startup_status: Optional[SpeechRequest] = None
        self._active_request: Optional[SpeechRequest] = None
        self._active_cancel_event: Optional[threading.Event] = None
        self._cancel_event_factory = threading.Event
        self._active_player: Optional[PlaybackPipeline] = None
        self._pause_requested = False
        self._decision_boundary = threading.RLock()
        self._shutdown = False
        self._thread = threading.Thread(
            target=self._run, name="piper-speech", daemon=True
        )
        self._thread.start()

    def set_sentence_pause_provider(
        self, provider: Callable[[], int]
    ) -> None:
        """Set the live Piper sentence-pause setting source."""
        self._sentence_pause_provider = provider

    def set_piper_sentence_streaming_provider(
        self, provider: Callable[[], bool]
    ) -> None:
        """Set the live Piper sentence-streaming setting source."""
        self._piper_sentence_streaming_provider = provider

    def toggle_pause(self) -> None:
        """Toggle pause for active speech, including synthesis before playback."""
        with self._condition:
            if self._active_request is None:
                return
            self._pause_requested = not self._pause_requested
            self._apply_pause_state(self._active_player, self._pause_requested)

    @staticmethod
    def _apply_pause_state(player, paused: bool) -> None:
        """Apply pause state when supported by the active playback object."""
        if player is None:
            return
        method = getattr(player, "pause" if paused else "resume", None)
        if callable(method):
            method()

    def submit(self, request: SpeechRequest) -> bool:
        """Queue a request according to its speech purpose."""
        cancel_active = False
        player = None
        cancel_event = None
        evicted_startup_status = None

        with self._condition:
            if self._shutdown:
                return False

            active_purpose = (
                self._active_request.purpose
                if self._active_request is not None
                else None
            )
            if request.purpose is SpeechPurpose.FOREGROUND:
                self._pending_foreground = request
                self._pending_errors.clear()
                self._pending_browser = None
                self._pending_codex = None
                self._pending_welcome = None
                evicted_startup_status = self._pending_startup_status
                self._pending_startup_status = None
                cancel_active = (
                    active_purpose is not None
                    and active_purpose is not SpeechPurpose.FOREGROUND
                )
            elif request.purpose is SpeechPurpose.ERROR:
                self._pending_errors.append(request)
                self._pending_browser = None
                self._pending_codex = None
                evicted_startup_status = self._pending_startup_status
                self._pending_startup_status = None
                cancel_active = active_purpose in {
                    SpeechPurpose.CODEX,
                    SpeechPurpose.WELCOME,
                    SpeechPurpose.STARTUP_STATUS,
                }
            elif request.purpose is SpeechPurpose.BROWSER:
                higher_pending = (
                    self._pending_foreground is not None
                    or bool(self._pending_errors)
                )
                higher_active = active_purpose in {
                    SpeechPurpose.FOREGROUND,
                    SpeechPurpose.ERROR,
                }
                if higher_pending or higher_active:
                    return False
                self._pending_browser = request
                self._pending_codex = None
                self._pending_welcome = None
                evicted_startup_status = self._pending_startup_status
                self._pending_startup_status = None
                cancel_active = active_purpose in {
                    SpeechPurpose.CODEX,
                    SpeechPurpose.WELCOME,
                    SpeechPurpose.STARTUP_STATUS,
                }
            elif request.purpose is SpeechPurpose.CODEX:
                higher_pending = (
                    self._pending_foreground is not None
                    or bool(self._pending_errors)
                    or self._pending_browser is not None
                )
                higher_active = active_purpose in {
                    SpeechPurpose.FOREGROUND,
                    SpeechPurpose.ERROR,
                    SpeechPurpose.BROWSER,
                }
                if higher_pending or higher_active:
                    return False
                self._pending_codex = request
                self._pending_welcome = None
                evicted_startup_status = self._pending_startup_status
                self._pending_startup_status = None
                cancel_active = active_purpose in {
                    SpeechPurpose.CODEX,
                    SpeechPurpose.WELCOME,
                    SpeechPurpose.STARTUP_STATUS,
                }
            elif request.purpose is SpeechPurpose.WELCOME:
                self._pending_welcome = request
                evicted_startup_status = self._pending_startup_status
                self._pending_startup_status = None
            else:
                evicted_startup_status = self._pending_startup_status
                self._pending_startup_status = request

            if cancel_active:
                self._pause_requested = False
                player = self._active_player
                cancel_event = self._active_cancel_event
            self._condition.notify()

        self._cancel_outside_condition(cancel_event, player)
        if evicted_startup_status is not None:
            self._on_event(
                SpeechEvent(
                    SpeechEventKind.CANCELLED,
                    evicted_startup_status.generation,
                    purpose=SpeechPurpose.STARTUP_STATUS,
                )
            )
        return True

    def _cancel_outside_condition(self, cancel_event, player) -> None:
        if cancel_event is not None:
            cancel_event.set()
        if player is not None:
            player.stop()
        if cancel_event is not None:
            with self._decision_boundary:
                cancel_event.set()

    def cancel_active(self, generation: int) -> None:
        """Cancel matching active work and discard a matching pending request."""
        player = None
        cancel_event = None
        with self._condition:
            if (
                self._pending_foreground is not None
                and self._pending_foreground.generation == generation
            ):
                self._pending_foreground = None

            if (
                self._active_request is None
                or self._active_request.purpose
                is not SpeechPurpose.FOREGROUND
                or self._active_request.generation != generation
            ):
                return
            self._pause_requested = False
            player = self._active_player
            cancel_event = self._active_cancel_event
        if cancel_event is not None:
            cancel_event.set()
        if player is not None:
            player.stop()
        if cancel_event is not None:
            with self._decision_boundary:
                cancel_event.set()

    def cancel_auxiliary(self) -> None:
        """Cancel active and pending error or welcome speech."""
        player = None
        cancel_event = None
        evicted_startup_status = None
        with self._condition:
            self._pending_errors.clear()
            self._pending_browser = None
            self._pending_codex = None
            self._pending_welcome = None
            evicted_startup_status = self._pending_startup_status
            self._pending_startup_status = None
            active = self._active_request
            if (
                active is not None
                and active.purpose is not SpeechPurpose.FOREGROUND
            ):
                self._pause_requested = False
                player = self._active_player
                cancel_event = self._active_cancel_event

        if cancel_event is not None or player is not None:
            self._cancel_outside_condition(cancel_event, player)
        if evicted_startup_status is not None:
            self._on_event(
                SpeechEvent(
                    SpeechEventKind.CANCELLED,
                    evicted_startup_status.generation,
                    purpose=SpeechPurpose.STARTUP_STATUS,
                )
            )

    def cancel_browser(self) -> None:
        """Cancel active and pending browser speech only."""
        player = None
        cancel_event = None
        with self._condition:
            self._pending_browser = None
            active = self._active_request
            if active is None or active.purpose is not SpeechPurpose.BROWSER:
                return
            self._pause_requested = False
            player = self._active_player
            cancel_event = self._active_cancel_event
        self._cancel_outside_condition(cancel_event, player)

    def cancel_codex(self) -> None:
        """Cancel active and pending Codex speech only."""
        player = None
        cancel_event = None
        with self._condition:
            self._pending_codex = None
            active = self._active_request
            if active is None or active.purpose is not SpeechPurpose.CODEX:
                return
            self._pause_requested = False
            player = self._active_player
            cancel_event = self._active_cancel_event
        self._cancel_outside_condition(cancel_event, player)

    def shutdown(self) -> None:
        """Stop active speech and wait briefly for the worker to finish."""
        with self._condition:
            self._shutdown = True
            self._pending_foreground = None
            self._pending_errors.clear()
            self._pending_browser = None
            self._pending_codex = None
            self._pending_welcome = None
            self._pending_startup_status = None
            player = self._active_player
            cancel_event = self._active_cancel_event
            self._condition.notify_all()
            self._pause_requested = False
        if player is not None:
            player.stop()
        if cancel_event is not None:
            with self._decision_boundary:
                cancel_event.set()
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                _LOGGER.error(
                    "speech shutdown timed_out=true thread=%s",
                    self._thread.name,
                )

    def _run(self) -> None:
        while True:
            with self._condition:
                while (
                    not self._has_pending_locked()
                    and not self._shutdown
                ):
                    self._condition.wait()
                if (
                    self._shutdown
                    and not self._has_pending_locked()
                ):
                    return
                request = self._take_next_locked()
                cancel_event = self._cancel_event_factory()
                self._active_request = request
                self._active_cancel_event = cancel_event
                self._pause_requested = False

            try:
                self._speak(request, cancel_event)
            finally:
                with self._condition:
                    self._active_request = None
                    self._active_cancel_event = None
                    self._active_player = None
                    self._pause_requested = False
                del request

    def _has_pending_locked(self) -> bool:
        return (
            self._pending_foreground is not None
            or bool(self._pending_errors)
            or self._pending_browser is not None
            or self._pending_codex is not None
            or self._pending_welcome is not None
            or self._pending_startup_status is not None
        )

    def _take_next_locked(self) -> SpeechRequest:
        if self._pending_foreground is not None:
            request = self._pending_foreground
            self._pending_foreground = None
            return request

        if self._pending_errors:
            return self._pending_errors.popleft()

        if self._pending_browser is not None:
            request = self._pending_browser
            self._pending_browser = None
            return request

        if self._pending_codex is not None:
            request = self._pending_codex
            self._pending_codex = None
            return request

        request = self._pending_welcome
        self._pending_welcome = None
        if request is not None:
            return request

        request = self._pending_startup_status
        self._pending_startup_status = None
        if request is None:
            raise RuntimeError("speech scheduler woke without pending work")
        return request

    @staticmethod
    def _piper_audio(
        voice, text, cancel_event, sentence_streaming_enabled
    ) -> Iterator[bytes | bytearray]:
        if not sentence_streaming_enabled:
            if cancel_event.is_set():
                return
            audio_buffer = bytearray()
            for chunk in voice.synthesize(text):
                if cancel_event.is_set():
                    return
                audio_buffer.extend(chunk.audio_int16_bytes)
            if not cancel_event.is_set() and audio_buffer:
                yield audio_buffer
            return

        # eSpeak can ignore periods followed by lowercase text. Split first so
        # those boundaries still produce separate audio chunks and pauses.
        for sentence in split_speech_sentences(text) or (text,):
            if cancel_event.is_set():
                return
            for chunk in voice.synthesize(sentence):
                if cancel_event.is_set():
                    return
                yield chunk.audio_int16_bytes

    def _speak(
        self,
        request: SpeechRequest,
        cancel_event: threading.Event,
    ) -> None:
        self._on_event(
            SpeechEvent(
                SpeechEventKind.STARTED,
                request.generation,
                purpose=request.purpose,
            )
        )
        terminal_kind = SpeechEventKind.FINISHED
        error: str | None = None
        failure_phase: str | None = None
        failure: BaseException | None = None
        phase = "synthesis"
        synthesis_seconds = 0.0
        release_backend = None
        audio_chunks = None
        sentence_stream = None
        try:
            if request.backend_override is not None:
                backend = request.backend_override
            else:
                provided_backend = self._voice_provider()
                if (
                    isinstance(provided_backend, tuple)
                    and len(provided_backend) == 2
                    and callable(provided_backend[1])
                ):
                    backend, release_backend = provided_backend
                else:
                    backend = provided_backend
            is_piper_voice = hasattr(backend, "config")
            sample_rate = backend.config.sample_rate if is_piper_voice else None
            sentence_streaming_enabled = False
            if not is_piper_voice:
                before_stream_init = time.monotonic()
                try:
                    sentence_stream = _BackendSentenceStream(
                        backend,
                        request.text,
                        cancel_event,
                    )
                except Exception:
                    # The constructor obtains the first result before a player
                    # can be created, so include a failed initial request too.
                    synthesis_seconds += time.monotonic() - before_stream_init
                    raise
                sample_rate = sentence_stream.sample_rate
                audio_chunks = sentence_stream
            else:
                sentence_streaming_enabled = (
                    self._piper_sentence_streaming_provider()
                )
                audio_chunks = self._piper_audio(
                    backend,
                    request.text,
                    cancel_event,
                    sentence_streaming_enabled,
                )
            phase = "playback"
            player_context = self._player_factory(sample_rate)
            with player_context as player:
                with self._condition:
                    self._active_player = player
                    cancelled = cancel_event.is_set()
                    if not cancelled and self._pause_requested:
                        self._apply_pause_state(player, paused=True)
                if cancelled:
                    player.stop()
                elif sentence_stream is not None:
                    phase = "synthesis"
                    sentence_stream.start()

                played_piper_sentence = False
                phase = "synthesis"
                while True:
                    phase = "synthesis"
                    if cancel_event.is_set():
                        terminal_kind = SpeechEventKind.CANCELLED
                        break
                    before_next = time.monotonic()
                    try:
                        chunk = next(audio_chunks)
                    except StopIteration:
                        if sentence_stream is None:
                            synthesis_seconds += time.monotonic() - before_next
                        break
                    except Exception:
                        if sentence_stream is None:
                            synthesis_seconds += time.monotonic() - before_next
                        raise
                    else:
                        if sentence_stream is None:
                            synthesis_seconds += time.monotonic() - before_next
                    if cancel_event.is_set():
                        terminal_kind = SpeechEventKind.CANCELLED
                        break
                    audio_bytes = chunk
                    if (
                        is_piper_voice
                        and sentence_streaming_enabled
                        and audio_bytes
                    ):
                        if played_piper_sentence:
                            # Piper yields one sentence per chunk. Queue PCM silence
                            # to preserve the audible boundary in streaming mode.
                            # The pitch pipeline applies tempo to silence too.
                            speed = 1 + getattr(player, "speed_percent", 0) / 100
                            sentence_pause_ms = self._sentence_pause_provider()
                            pause_frames = round(
                                sample_rate * sentence_pause_ms / 1000 * speed
                            )
                            audio_bytes = bytes(pause_frames * 2) + bytes(audio_bytes)
                        is_nonempty_streamed_piper_audio = True
                    else:
                        is_nonempty_streamed_piper_audio = False
                    if cancel_event.is_set():
                        terminal_kind = SpeechEventKind.CANCELLED
                        break
                    with self._decision_boundary:
                        if cancel_event.is_set():
                            terminal_kind = SpeechEventKind.CANCELLED
                            break
                        phase = "playback"
                        player.play(audio_bytes)
                        if is_nonempty_streamed_piper_audio:
                            played_piper_sentence = True

                if cancel_event.is_set():
                    terminal_kind = SpeechEventKind.CANCELLED
                phase = "playback"
        except Exception as caught:
            if cancel_event.is_set():
                terminal_kind = SpeechEventKind.CANCELLED
            else:
                terminal_kind = SpeechEventKind.FAILED
                failure = caught
                failure_phase = phase
                error = (
                    "Speech playback failed."
                    if phase == "playback"
                    else "Speech synthesis failed."
                )
        finally:
            cleanup_error = None
            try:
                if sentence_stream is not None:
                    sentence_stream.close()
                    synthesis_seconds += sentence_stream.synthesis_seconds
                else:
                    close_chunks = getattr(audio_chunks, "close", None)
                    if callable(close_chunks):
                        close_chunks()
            except Exception as caught:
                cleanup_error = caught
                if sentence_stream is not None:
                    synthesis_seconds += sentence_stream.synthesis_seconds
            finally:
                if release_backend is not None:
                    try:
                        release_backend()
                    except Exception as caught:
                        if cleanup_error is None:
                            cleanup_error = caught

            if (
                cleanup_error is not None
                and failure is None
                and not cancel_event.is_set()
            ):
                terminal_kind = SpeechEventKind.FAILED
                failure = cleanup_error
                failure_phase = "synthesis"
                error = "Speech synthesis failed."

        with self._decision_boundary:
            if cancel_event.is_set():
                terminal_kind = SpeechEventKind.CANCELLED
                error = None
            elapsed_ms = int(synthesis_seconds * 1000)
            log_synthesis_result(
                _LOGGER,
                request.generation,
                elapsed_ms,
                terminal_kind.name,
            )
            if terminal_kind is SpeechEventKind.FAILED and failure is not None:
                log_exception_safe(
                    _LOGGER,
                    "speech failure",
                    failure,
                    generation=request.generation,
                    phase=failure_phase,
                )
            self._on_event(
                SpeechEvent(
                    terminal_kind,
                    request.generation,
                    error,
                    failure_phase,
                    request.purpose,
                )
            )
