"""Ordered physical teardown for the Windows tray application."""

import threading
from typing import Callable


Cleanup = Callable[[], None]
FailureCallback = Callable[[str, BaseException], None]


class TeardownCoordinator:
    def __init__(
        self,
        *,
        stop_hotkeys: Cleanup,
        stop_power: Cleanup,
        stop_speech: Cleanup,
        stop_tray: Cleanup,
        close_instance: Cleanup,
        quit_root: Cleanup,
        on_failure: FailureCallback,
        on_complete: Cleanup,
    ) -> None:
        self._steps = (
            ("hotkeys", stop_hotkeys),
            ("power", stop_power),
            ("speech", stop_speech),
            ("tray", stop_tray),
            ("instance", close_instance),
            ("tk", quit_root),
        )
        self._on_failure = on_failure
        self._on_complete = on_complete
        self._lock = threading.Lock()
        self._started = False

    def run(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True

        for stage, cleanup in self._steps:
            try:
                cleanup()
            except Exception as error:
                try:
                    self._on_failure(stage, error)
                except Exception:
                    # Failure reporting must never prevent later resources from
                    # being released during teardown.
                    pass

        try:
            self._on_complete()
        except Exception:
            # Completion reporting is diagnostic-only and must not turn a
            # completed teardown into an application failure.
            pass
