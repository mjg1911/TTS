from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Callable, Optional, Tuple


VOICE_SWITCH_SUCCEEDED = "VOICE_SWITCH_SUCCEEDED"
VOICE_SWITCH_FAILED = "VOICE_SWITCH_FAILED"


@dataclass(frozen=True)
class VoiceSwitchEvent:
    generation: int
    success: bool
    model_path: Optional[Path] = None
    voice: Optional[object] = None
    error: Optional[BaseException] = None


class VoiceManager:
    def __init__(
        self,
        voice: object,
        load_candidate: Callable[[str], Tuple[Path, object]],
    ) -> None:
        self._voice = voice
        self._load_candidate = load_candidate
        self._lock = threading.Lock()
        self._threads = []

    def current(self) -> object:
        with self._lock:
            return self._voice

    def replace(self, voice: object) -> None:
        with self._lock:
            self._voice = voice

    def begin_switch(
        self,
        reference: str,
        generation: int,
        emit: Callable[[VoiceSwitchEvent], None],
    ) -> None:
        def load() -> None:
            try:
                model_path, candidate = self._load_candidate(reference)
            except Exception as error:
                emit(VoiceSwitchEvent(generation, False, error=error))
                return
            emit(VoiceSwitchEvent(generation, True, model_path, candidate))

        thread = threading.Thread(target=load, name="piper-voice-load", daemon=True)
        self._threads.append(thread)
        thread.start()

    def join_for_test(self) -> None:
        for thread in self._threads:
            thread.join()
