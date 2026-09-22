from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from typing import Callable, Tuple


class BackendPreparationError(RuntimeError):
    """Raised when a replacement backend cannot be made ready."""


def _noop() -> None:
    return None


def _safe_close(close: Callable[[], None]) -> None:
    try:
        close()
    except (OSError, RuntimeError):
        return None


@dataclass
class BackendCandidate:
    engine: str
    voice_id: str
    backend: object
    close: Callable[[], None] = _noop
    _released: bool = field(default=False, init=False, repr=False)

    def release_for_commit(self) -> Tuple[object, Callable[[], None]]:
        if self._released:
            raise RuntimeError("candidate ownership already released")
        self._released = True
        return self.backend, self.close

    def discard(self) -> None:
        if self._released:
            return
        self._released = True
        _safe_close(self.close)


class BackendManager:
    def __init__(
        self,
        backend: object,
        close_backend: Callable[[], None],
        prepare_backend: Callable[[str, str], BackendCandidate],
    ) -> None:
        self._backend = backend
        self._close_backend = close_backend
        self._prepare_backend = prepare_backend
        self._lock = Lock()

    def current(self) -> object:
        with self._lock:
            return self._backend

    def prepare(self, engine: str, voice_id: str) -> BackendCandidate:
        return self._prepare_backend(engine, voice_id)

    def discard(self, candidate: BackendCandidate) -> None:
        candidate.discard()

    def commit(self, candidate: BackendCandidate) -> None:
        backend, close_backend = candidate.release_for_commit()
        with self._lock:
            old_close = self._close_backend
            self._backend = backend
            self._close_backend = close_backend
        _safe_close(old_close)

    def shutdown(self) -> None:
        with self._lock:
            close_backend = self._close_backend
            self._close_backend = _noop
        _safe_close(close_backend)
