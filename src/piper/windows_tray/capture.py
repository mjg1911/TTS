"""Fresh selected-text capture using simulated Ctrl+C and clipboard polling."""

import logging
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, Optional, Any

from .logging_setup import log_exception_safe


_LOGGER = logging.getLogger(__name__)


HOTKEY_RELEASE_DELAY_S = 0.15


class CaptureStatus(Enum):
    SUCCESS = auto()
    TIMEOUT = auto()
    EMPTY = auto()
    ACCESS_ERROR = auto()


@dataclass(frozen=True)
class CaptureResult:
    status: CaptureStatus
    text: Optional[str] = None
    detail: Optional[str] = None


class SelectionCapture:
    def __init__(
        self,
        clipboard: Any,
        send_copy: Callable[[], None],
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._clipboard = clipboard
        self._send_copy = send_copy
        self._monotonic = monotonic
        self._sleep = sleep

    def capture(self, timeout_s: float = 1.0, poll_s: float = 0.05) -> CaptureResult:
        try:
            before = self._clipboard.sequence_number()
            self._sleep(HOTKEY_RELEASE_DELAY_S)
            self._send_copy()
        except OSError as error:
            log_exception_safe(
                _LOGGER,
                "capture access failure",
                error,
                stage="initial_copy",
            )
            return CaptureResult(CaptureStatus.ACCESS_ERROR, detail=str(error))

        deadline = self._monotonic() + timeout_s
        sequence_changed = False
        last_error: Optional[OSError] = None
        saw_sequence_error = False

        while self._monotonic() < deadline:
            try:
                current = self._clipboard.sequence_number()
            except OSError as error:
                log_exception_safe(
                    _LOGGER,
                    "capture access failure",
                    error,
                    stage="sequence_poll",
                )
                last_error = error
                saw_sequence_error = True
            else:
                if current != before:
                    sequence_changed = True
                    try:
                        text = self._clipboard.read_text()
                    except OSError as error:
                        log_exception_safe(
                            _LOGGER,
                            "capture access failure",
                            error,
                            stage="clipboard_read",
                        )
                        last_error = error
                    else:
                        text = text.rstrip("\x00")
                        if text.strip():
                            return CaptureResult(CaptureStatus.SUCCESS, text)
            self._sleep(poll_s)

        if sequence_changed:
            if last_error is not None:
                return CaptureResult(CaptureStatus.ACCESS_ERROR, detail=str(last_error))
            return CaptureResult(CaptureStatus.EMPTY)
        if saw_sequence_error:
            return CaptureResult(CaptureStatus.ACCESS_ERROR, detail=str(last_error))
        return CaptureResult(CaptureStatus.TIMEOUT)
