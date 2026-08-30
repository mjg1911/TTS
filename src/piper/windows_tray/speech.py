"""Background speech synthesis and playback coordination for the tray app."""

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
import logging
import threading
import time
from typing import Optional

from piper.audio_playback import AudioPlayer

from .logging_setup import log_exception_safe, log_synthesis_result
from .pitch_playback import PlaybackPipeline


_LOGGER = logging.getLogger(__name__)


class SpeechEventKind(Enum):
    STARTED = auto()
    FINISHED = auto()
    CANCELLED = auto()
    FAILED = auto()


class SpeechPurpose(Enum):
    FOREGROUND = auto()
    ERROR = auto()
    WELCOME = auto()


@dataclass(frozen=True)
class SpeechRequest:
    generation: int
    text: str
    purpose: SpeechPurpose = SpeechPurpose.FOREGROUND


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
        self._condition = threading.Condition()
        self._pending_foreground: Optional[SpeechRequest] = None
        self._pending_errors = deque()  # type: deque[SpeechRequest]
        self._pending_welcome: Optional[SpeechRequest] = None
        self._active_request: Optional[SpeechRequest] = None
        self._active_cancel_event: Optional[threading.Event] = None
        self._cancel_event_factory = threading.Event
        self._active_player: Optional[PlaybackPipeline] = None
        self._decision_boundary = threading.RLock()
        self._shutdown = False
        self._thread = threading.Thread(
            target=self._run, name="piper-speech", daemon=True
        )
        self._thread.start()

    def submit(self, request: SpeechRequest) -> None:
        """Queue a request according to its speech purpose."""
        cancel_auxiliary = False
        player = None
        cancel_event = None

        with self._condition:
            if self._shutdown:
                return

            if request.purpose is SpeechPurpose.FOREGROUND:
                self._pending_foreground = request
                self._pending_errors.clear()
                self._pending_welcome = None
                cancel_auxiliary = (
                    self._active_request is not None
                    and self._active_request.purpose
                    is not SpeechPurpose.FOREGROUND
                )
                if cancel_auxiliary:
                    player = self._active_player
                    cancel_event = self._active_cancel_event
            elif request.purpose is SpeechPurpose.ERROR:
                self._pending_errors.append(request)
            else:
                self._pending_welcome = request

            self._condition.notify()

        if cancel_auxiliary:
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
        with self._condition:
            self._pending_errors.clear()
            self._pending_welcome = None
            active = self._active_request
            if (
                active is None
                or active.purpose is SpeechPurpose.FOREGROUND
            ):
                return
            player = self._active_player
            cancel_event = self._active_cancel_event

        if cancel_event is not None:
            cancel_event.set()
        if player is not None:
            player.stop()
        if cancel_event is not None:
            with self._decision_boundary:
                cancel_event.set()

    def shutdown(self) -> None:
        """Stop active speech and wait briefly for the worker to finish."""
        with self._condition:
            self._shutdown = True
            self._pending_foreground = None
            self._pending_errors.clear()
            self._pending_welcome = None
            player = self._active_player
            cancel_event = self._active_cancel_event
            self._condition.notify_all()
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

            self._speak(request, cancel_event)

            with self._condition:
                self._active_request = None
                self._active_cancel_event = None
                self._active_player = None

    def _has_pending_locked(self) -> bool:
        return (
            self._pending_foreground is not None
            or bool(self._pending_errors)
            or self._pending_welcome is not None
        )

    def _take_next_locked(self) -> SpeechRequest:
        if self._pending_foreground is not None:
            request = self._pending_foreground
            self._pending_foreground = None
            return request

        if self._pending_errors:
            return self._pending_errors.popleft()

        request = self._pending_welcome
        self._pending_welcome = None
        if request is None:
            raise RuntimeError(
                "speech scheduler woke without pending work"
            )
        return request

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
        try:
            voice = self._voice_provider()
            sample_rate = voice.config.sample_rate
            phase = "playback"
            player_context = self._player_factory(sample_rate)
            with player_context as player:
                with self._condition:
                    self._active_player = player
                    cancelled = cancel_event.is_set()
                if cancelled:
                    player.stop()

                phase = "synthesis"
                audio_chunks = iter(voice.synthesize(request.text))
                while True:
                    phase = "synthesis"
                    if cancel_event.is_set():
                        terminal_kind = SpeechEventKind.CANCELLED
                        break
                    before_next = time.monotonic()
                    try:
                        chunk = next(audio_chunks)
                    except StopIteration:
                        synthesis_seconds += time.monotonic() - before_next
                        break
                    except Exception:
                        synthesis_seconds += time.monotonic() - before_next
                        raise
                    else:
                        synthesis_seconds += time.monotonic() - before_next
                    if cancel_event.is_set():
                        terminal_kind = SpeechEventKind.CANCELLED
                        break
                    audio_bytes = chunk.audio_int16_bytes
                    if cancel_event.is_set():
                        terminal_kind = SpeechEventKind.CANCELLED
                        break
                    with self._decision_boundary:
                        if cancel_event.is_set():
                            terminal_kind = SpeechEventKind.CANCELLED
                            break
                        phase = "playback"
                        player.play(audio_bytes)

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
