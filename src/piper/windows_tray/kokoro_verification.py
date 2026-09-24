"""Background execution for explicit Kokoro integrity verification."""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Callable, Optional


@dataclass(frozen=True)
class KokoroVerificationResult:
    succeeded: bool
    message: str


class KokoroVerificationCoordinator:
    def __init__(self, verify: Callable[[], object], logger) -> None:
        self._verify = verify
        self._logger = logger
        self._lock = threading.Lock()
        self._running = False
        self._result: Optional[KokoroVerificationResult] = None

    def start(self) -> bool:
        with self._lock:
            if self._running:
                return False
            self._running = True
            self._result = None

        threading.Thread(
            target=self._run,
            name="kokoro-integrity-verification",
            daemon=True,
        ).start()
        return True

    def _run(self) -> None:
        try:
            self._verify()
        except Exception as error:
            self._logger.warning(
                "Kokoro integrity verification failed error_type=%s",
                type(error).__name__,
            )
            result = KokoroVerificationResult(
                False,
                "Kokoro verification failed. Some installed files are missing or corrupted.",
            )
        else:
            result = KokoroVerificationResult(
                True,
                "Kokoro files verified successfully.",
            )

        with self._lock:
            self._result = result
            self._running = False

    def take_result(self) -> Optional[KokoroVerificationResult]:
        with self._lock:
            result = self._result
            self._result = None
            return result
