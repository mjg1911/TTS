"""Background speech synthesis and playback coordination for the tray app."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
import threading
from typing import Optional

from piper.audio_playback import AudioPlayer


class SpeechEventKind(Enum):
    STARTED = auto()
    FINISHED = auto()
    CANCELLED = auto()
    FAILED = auto()


@dataclass(frozen=True)
class SpeechRequest:
    generation: int
    text: str


@dataclass(frozen=True)
class SpeechEvent:
    kind: SpeechEventKind
    generation: int
    error: str | None = None


class SpeechWorker:
    """Run synthesis and playback away from the tray controller thread."""

    def __init__(
        self,
        voice_provider: Callable[[], object],
        on_event: Callable[[SpeechEvent], None],
        player_factory: Callable[[int], AudioPlayer] = AudioPlayer,
    ) -> None:
        self._voice_provider = voice_provider
        self._on_event = on_event
        self._player_factory = player_factory
        self._condition = threading.Condition()
        self._pending: Optional[SpeechRequest] = None
        self._active_generation: Optional[int] = None
        self._cancel_event = threading.Event()
        self._active_player: Optional[AudioPlayer] = None
        self._decision_boundary = threading.RLock()
        self._shutdown = False
        self._thread = threading.Thread(
            target=self._run, name="piper-speech", daemon=True
        )
        self._thread.start()

    def submit(self, request: SpeechRequest) -> None:
        """Queue a request, replacing any request not yet started."""
        with self._condition:
            if self._shutdown:
                return
            self._pending = request
            self._condition.notify()

    def cancel_active(self, generation: int) -> None:
        """Cancel matching active work and discard a matching pending request."""
        with self._condition:
            if self._pending is not None and self._pending.generation == generation:
                self._pending = None
            if self._active_generation != generation:
                return
            player = self._active_player
        if player is not None:
            player.stop()
        with self._decision_boundary:
            self._cancel_event.set()

    def shutdown(self) -> None:
        """Stop active speech and wait briefly for the worker to finish."""
        with self._condition:
            self._shutdown = True
            self._pending = None
            player = self._active_player
            self._condition.notify_all()
        if player is not None:
            player.stop()
        with self._decision_boundary:
            self._cancel_event.set()
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while True:
            with self._condition:
                while self._pending is None and not self._shutdown:
                    self._condition.wait()
                if self._shutdown and self._pending is None:
                    return
                request = self._pending
                self._pending = None
                self._active_generation = request.generation
                self._cancel_event.clear()

            self._speak(request)

            with self._condition:
                self._active_generation = None
                self._active_player = None

    def _speak(self, request: SpeechRequest) -> None:
        self._on_event(SpeechEvent(SpeechEventKind.STARTED, request.generation))
        terminal_kind = SpeechEventKind.FINISHED
        error: str | None = None
        phase = "playback"
        try:
            voice = self._voice_provider()
            sample_rate = voice.config.sample_rate
            player_context = self._player_factory(sample_rate)
            with player_context as player:
                with self._condition:
                    self._active_player = player
                    cancelled = self._cancel_event.is_set()
                if cancelled:
                    player.stop()

                phase = "synthesis"
                audio_chunks = iter(voice.synthesize(request.text))
                while True:
                    phase = "synthesis"
                    if self._cancel_event.is_set():
                        terminal_kind = SpeechEventKind.CANCELLED
                        break
                    try:
                        chunk = next(audio_chunks)
                    except StopIteration:
                        break
                    if self._cancel_event.is_set():
                        terminal_kind = SpeechEventKind.CANCELLED
                        break
                    audio_bytes = chunk.audio_int16_bytes
                    if self._cancel_event.is_set():
                        terminal_kind = SpeechEventKind.CANCELLED
                        break
                    with self._decision_boundary:
                        if self._cancel_event.is_set():
                            terminal_kind = SpeechEventKind.CANCELLED
                            break
                        phase = "playback"
                        player.play(audio_bytes)

                if self._cancel_event.is_set():
                    terminal_kind = SpeechEventKind.CANCELLED
        except Exception:
            if self._cancel_event.is_set():
                terminal_kind = SpeechEventKind.CANCELLED
            elif terminal_kind is not SpeechEventKind.CANCELLED:
                terminal_kind = SpeechEventKind.FAILED
                error = (
                    "Speech playback failed."
                    if phase == "playback"
                    else "Speech synthesis failed."
                )

        with self._decision_boundary:
            if self._cancel_event.is_set():
                terminal_kind = SpeechEventKind.CANCELLED
                error = None
            self._on_event(SpeechEvent(terminal_kind, request.generation, error))
