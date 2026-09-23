"""Background coordination for initial Kokoro readiness."""

from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, Queue
from threading import Condition, Event, Lock, Thread
import time
from types import MappingProxyType
from typing import Callable, Mapping, Optional, Tuple


# KokoroWorkerClient.shutdown() waits at most twice for its worker process.
# Leave a small margin for callback scheduling and let cancellation remain bounded.
CANCEL_WAIT_SECONDS = 5.0


class StartupCancelEvent(Event):
    """An Event that lets startup register cleanup for resources under construction.

    Cleanup callbacks run on daemon threads so a misbehaving callback cannot make
    cancellation unbounded. Each callback is claimed and invoked at most once;
    registering after cancellation dispatches it immediately.
    """

    def __init__(self, logger) -> None:
        super().__init__()
        self._logger = logger
        self._callbacks_lock = Lock()
        self._callbacks_changed = Condition(self._callbacks_lock)
        self._callbacks = []
        self._cleanup_in_flight = 0

    def register_cancel_cleanup(self, callback: Callable[[], None]) -> None:
        if not callable(callback):
            raise TypeError("cancel cleanup must be callable")
        with self._callbacks_lock:
            if not self.is_set():
                self._callbacks.append(callback)
                return
        self._dispatch(callback)

    def set(self) -> None:
        with self._callbacks_lock:
            if self.is_set():
                return
            super().set()
            callbacks, self._callbacks = self._callbacks, []
        for callback in callbacks:
            self._dispatch(callback)

    def _dispatch(self, callback: Callable[[], None]) -> None:
        def run() -> None:
            try:
                callback()
            except Exception as error:
                self._logger.error(
                    "Kokoro startup cleanup failed stage=cancel_cleanup "
                    "exception_type=%s",
                    type(error).__name__,
                )
            finally:
                with self._callbacks_changed:
                    self._cleanup_in_flight -= 1
                    self._callbacks_changed.notify_all()

        thread = Thread(target=run, name="kokoro-startup-cleanup", daemon=True)
        with self._callbacks_changed:
            self._cleanup_in_flight += 1
            thread.start()

    def wait_for_cleanup(self, deadline: float, monotonic: Callable[[], float]) -> bool:
        with self._callbacks_changed:
            while self._cleanup_in_flight:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return False
                self._callbacks_changed.wait(timeout=remaining)
            return True


@dataclass(frozen=True)
class KokoroStartupResult:
    candidate: Optional[object]
    voice_ids: Tuple[str, ...]
    unavailable_reason: Optional[str]
    stage_durations: Mapping[str, float]

    def __post_init__(self) -> None:
        if (self.candidate is None) == (self.unavailable_reason is None):
            raise ValueError("startup result must contain exactly one outcome")
        object.__setattr__(self, "voice_ids", tuple(self.voice_ids))
        object.__setattr__(
            self, "stage_durations", MappingProxyType(dict(self.stage_durations))
        )


class KokoroStartupCoordinator:
    """Run a startup job off-thread and transfer its result once to the caller.

    ``startup_job`` returns ``(candidate, voice_ids)``. It may register active
    client cleanup with ``cancel_event.register_cancel_cleanup(client.shutdown)``.
    ``record_timing(stage, operation)`` runs and times one startup stage.
    """

    def __init__(
        self,
        startup_job: Callable,
        logger,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._startup_job = startup_job
        self._logger = logger
        self._monotonic = monotonic
        self._cancel_event = StartupCancelEvent(logger)
        self._results: Queue[KokoroStartupResult] = Queue(maxsize=1)
        self._lock = Lock()
        self._started = False
        self._cancelled = False
        self._stage_durations = {}
        self._current_stage = "initialization"
        self._thread = Thread(
            target=self._run,
            name="kokoro-startup",
            daemon=True,
        )

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            if not self._cancelled:
                self._thread.start()

    def cancel(self) -> None:
        with self._lock:
            if self._cancelled:
                return
            self._cancelled = True
            self._discard_queued_candidate()
            started = self._started
        deadline = self._monotonic() + CANCEL_WAIT_SECONDS
        self._cancel_event.set()
        worker_finished = True
        if started:
            self._thread.join(timeout=max(0.0, deadline - self._monotonic()))
            worker_finished = not self._thread.is_alive()
        cleanup_finished = self._cancel_event.wait_for_cleanup(
            deadline, self._monotonic
        )
        if not worker_finished or not cleanup_finished:
            self._logger.error(
                "Kokoro startup cancellation timed out stage=shutdown"
            )

    def take_result(self) -> Optional[KokoroStartupResult]:
        with self._lock:
            try:
                return self._results.get_nowait()
            except Empty:
                return None

    def _run(self) -> None:
        candidate = None

        def record_timing(stage: str, operation: Callable[[], object]):
            with self._lock:
                self._current_stage = stage
            started = self._monotonic()
            try:
                return operation()
            finally:
                elapsed = max(0.0, self._monotonic() - started)
                with self._lock:
                    self._stage_durations[stage] = elapsed

        try:
            candidate, voice_ids = self._startup_job(self._cancel_event, record_timing)
            result = KokoroStartupResult(
                candidate=candidate,
                voice_ids=tuple(voice_ids),
                unavailable_reason=None,
                stage_durations=self._timing_snapshot(),
            )
        except Exception as error:
            self._discard_candidate(candidate)
            with self._lock:
                stage = self._current_stage
            self._logger.error(
                "Kokoro startup failed stage=%s exception_type=%s",
                stage,
                type(error).__name__,
            )
            result = KokoroStartupResult(
                candidate=None,
                voice_ids=(),
                unavailable_reason="Kokoro is unavailable during startup.",
                stage_durations=self._timing_snapshot(),
            )

        with self._lock:
            if self._cancelled:
                self._discard_candidate(result.candidate)
                return
            self._results.put_nowait(result)

    def _timing_snapshot(self) -> Mapping[str, float]:
        with self._lock:
            return dict(self._stage_durations)

    def _discard_queued_candidate(self) -> None:
        try:
            result = self._results.get_nowait()
        except Empty:
            return
        self._discard_candidate(result.candidate)

    def _discard_candidate(self, candidate) -> None:
        if candidate is None:
            return
        discard = getattr(candidate, "discard", None)
        if callable(discard):
            close = discard
        else:
            close = getattr(candidate, "close", None)
        if callable(close):
            try:
                close()
            except Exception as error:
                self._logger.error(
                    "Kokoro startup candidate cleanup failed stage=candidate_cleanup "
                    "exception_type=%s",
                    type(error).__name__,
                )
