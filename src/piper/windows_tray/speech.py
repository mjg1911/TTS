"""Background speech synthesis and playback coordination for the tray app."""

from __future__ import annotations

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
    BROWSER = auto()
    CODEX = auto()
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
        self._pending_browser: Optional[SpeechRequest] = None
        self._pending_codex: Optional[SpeechRequest] = None
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

    def submit(self, request: SpeechRequest) -> bool:
        """Queue a request according to its speech purpose."""
        cancel_active = False
        player = None
        cancel_event = None

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
                cancel_active = (
                    active_purpose is not None
                    and active_purpose is not SpeechPurpose.FOREGROUND
                )
            elif request.purpose is SpeechPurpose.ERROR:
                self._pending_errors.append(request)
                self._pending_browser = None
                self._pending_codex = None
                cancel_active = active_purpose in {
                    SpeechPurpose.CODEX,
                    SpeechPurpose.WELCOME,
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
                cancel_active = active_purpose in {
                    SpeechPurpose.CODEX,
                    SpeechPurpose.WELCOME,
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
                cancel_active = active_purpose in {
                    SpeechPurpose.CODEX,
                    SpeechPurpose.WELCOME,
                }
            else:
                self._pending_welcome = request

            if cancel_active:
                player = self._active_player
                cancel_event = self._active_cancel_event
            self._condition.notify()

        self._cancel_outside_condition(cancel_event, player)
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
            self._pending_browser = None
            self._pending_codex = None
            self._pending_welcome = None
            active = self._active_request
            if (
                active is None
                or active.purpose is SpeechPurpose.FOREGROUND
            ):
                return
            player = self._active_player
            cancel_event = self._active_cancel_event

        self._cancel_outside_condition(cancel_event, player)

    def cancel_browser(self) -> None:
        """Cancel active and pending browser speech only."""
        player = None
        cancel_event = None
        with self._condition:
            self._pending_browser = None
            active = self._active_request
            if active is None or active.purpose is not SpeechPurpose.BROWSER:
                return
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
            or self._pending_browser is not None
            or self._pending_codex is not None
            or self._pending_welcome is not None
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
