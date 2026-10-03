import threading
import time

import piper.windows_tray.backend_startup as startup_module
from piper.windows_tray.backend_startup import (
    BackendStartupCoordinator,
    BackendStartupResult,
)
from piper.windows_tray.backend_manager import BackendCandidate, BackendManager


class RecordingLogger:
    def __init__(self):
        self.errors = []

    def error(self, message, *args):
        self.errors.append(message % args if args else message)


class Candidate:
    def __init__(self):
        self.close_calls = 0

    def close(self):
        self.close_calls += 1


def wait_until_result(coordinator):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        result = coordinator.take_result()
        if result is not None:
            return result
        time.sleep(0.005)
    raise AssertionError("startup result was not delivered")


def test_start_returns_while_job_is_blocked_and_delivers_once_off_worker_thread():
    entered = threading.Event()
    release = threading.Event()
    worker_threads = []
    candidate = Candidate()
    logger = RecordingLogger()

    def startup_job(_cancel_event, _record_timing):
        worker_threads.append(threading.current_thread())
        entered.set()
        assert release.wait(2)
        return candidate, ("default",)

    coordinator = BackendStartupCoordinator(startup_job, logger)
    caller_thread = threading.current_thread()
    before = time.monotonic()
    coordinator.start()
    elapsed = time.monotonic() - before

    assert entered.wait(1)
    assert elapsed < 0.5
    assert coordinator.take_result() is None
    release.set()
    result = wait_until_result(coordinator)

    assert result.candidate is candidate
    assert result.voice_ids == ("default",)
    assert result.unavailable_reason is None
    assert worker_threads[0] is not caller_thread
    assert coordinator.take_result() is None


def test_stage_timings_are_recorded_separately_and_immutable():
    ticks = iter((10.0, 11.25, 20.0, 22.5))
    candidate = Candidate()

    def startup_job(_cancel_event, record_timing):
        record_timing("installation", lambda: "installed")
        record_timing("readiness", lambda: "ready")
        return candidate, ("default",)

    coordinator = BackendStartupCoordinator(
        startup_job, RecordingLogger(), monotonic=lambda: next(ticks)
    )
    coordinator.start()
    result = wait_until_result(coordinator)

    assert result.stage_durations == {"installation": 1.25, "readiness": 2.5}
    try:
        result.stage_durations["installation"] = 0
    except TypeError:
        pass
    else:
        raise AssertionError("stage timings must be immutable")


def test_startup_exception_becomes_stable_unavailable_result_and_is_logged():
    logger = RecordingLogger()

    def startup_job(_cancel_event, _record_timing):
        raise RuntimeError("private detail")

    coordinator = BackendStartupCoordinator(startup_job, logger)
    coordinator.start()
    result = wait_until_result(coordinator)

    assert result.candidate is None
    assert result.unavailable_reason == "Backend is unavailable during startup."
    assert "exception_type=RuntimeError" in logger.errors[0]
    assert "stage=initialization" in logger.errors[0]
    assert "private detail" not in logger.errors[0]


def test_candidate_is_closed_if_result_conversion_fails_after_job_returns():
    candidate = Candidate()

    class InvalidVoiceIds:
        def __iter__(self):
            raise ValueError("invalid ids")

    def startup_job(_cancel_event, _record_timing):
        return candidate, InvalidVoiceIds()

    coordinator = BackendStartupCoordinator(startup_job, RecordingLogger())
    coordinator.start()
    result = wait_until_result(coordinator)

    assert candidate.close_calls == 1
    assert result.candidate is None
    assert result.unavailable_reason == "Backend is unavailable during startup."


def test_cancel_invokes_registered_cleanup_once_and_discards_late_candidate():
    waiting = threading.Event()
    release = threading.Event()
    cleaned = []
    candidate = Candidate()

    def startup_job(cancel_event, _record_timing):
        def cleanup():
            cleaned.append(True)
            release.set()

        cancel_event.register_cancel_cleanup(cleanup)
        waiting.set()
        release.wait(2)
        return candidate, ("default",)

    coordinator = BackendStartupCoordinator(startup_job, RecordingLogger())
    coordinator.start()
    assert waiting.wait(1)

    coordinator.cancel()

    assert len(cleaned) == 1
    assert candidate.close_calls == 1
    assert coordinator.take_result() is None


def test_cancel_unblocks_registered_readiness_cleanup_without_delivering_result():
    readiness_started = threading.Event()
    readiness_finished = threading.Event()
    worker = {"running": True, "shutdown_calls": 0}

    def shutdown_worker():
        worker["running"] = False
        worker["shutdown_calls"] += 1
        readiness_finished.set()

    def startup_job(cancel_event, record_timing):
        readiness_started.set()
        cancel_event.register_cancel_cleanup(shutdown_worker)
        cancel_event.wait(2)
        return Candidate(), ("default",)

    coordinator = BackendStartupCoordinator(startup_job, RecordingLogger())
    coordinator.start()
    assert readiness_started.wait(1)

    coordinator.cancel()

    assert readiness_finished.is_set()
    assert worker == {"running": False, "shutdown_calls": 1}
    assert coordinator.take_result() is None


def test_cleanup_registered_after_cancel_runs_once():
    waiting = threading.Event()
    released = threading.Event()
    cleanup_calls = []

    def startup_job(cancel_event, _record_timing):
        waiting.set()
        cancel_event.wait(2)
        cancel_event.register_cancel_cleanup(lambda: (cleanup_calls.append(True), released.set()))
        return Candidate(), ("default",)

    coordinator = BackendStartupCoordinator(startup_job, RecordingLogger())
    coordinator.start()
    assert waiting.wait(1)
    coordinator.cancel()

    assert released.wait(1)
    assert cleanup_calls == [True]
    assert coordinator.take_result() is None


def test_cancel_returns_within_configured_bound_when_cleanup_blocks(monkeypatch):
    cleanup_started = threading.Event()
    cleanup_release = threading.Event()
    startup_release = threading.Event()
    cleanup_registered = threading.Event()

    def startup_job(cancel_event, _record_timing):
        def blocked_cleanup():
            cleanup_started.set()
            cleanup_release.wait(2)

        cancel_event.register_cancel_cleanup(blocked_cleanup)
        cleanup_registered.set()
        startup_release.wait(2)
        return Candidate(), ("default",)

    monkeypatch.setattr(startup_module, "CANCEL_WAIT_SECONDS", 0.05)
    logger = RecordingLogger()
    coordinator = BackendStartupCoordinator(startup_job, logger)
    coordinator.start()
    assert cleanup_registered.wait(1)
    before = time.monotonic()
    coordinator.cancel()
    elapsed = time.monotonic() - before
    startup_release.set()
    cleanup_release.set()

    assert elapsed < 0.5
    assert cleanup_started.is_set()
    assert "stage=shutdown" in logger.errors[-1]


def test_cancel_waits_for_cleanup_registered_after_cancellation_starts():
    allow_registration = threading.Event()
    cleanup_started = threading.Event()
    cleanup_release = threading.Event()
    cancel_finished = threading.Event()

    def startup_job(cancel_event, _record_timing):
        cancel_event.wait(2)
        assert allow_registration.wait(2)

        def cleanup():
            cleanup_started.set()
            cleanup_release.wait(2)

        cancel_event.register_cancel_cleanup(cleanup)
        return Candidate(), ("default",)

    coordinator = BackendStartupCoordinator(startup_job, RecordingLogger())
    coordinator.start()
    cancel_thread = threading.Thread(
        target=lambda: (coordinator.cancel(), cancel_finished.set())
    )
    cancel_thread.start()
    allow_registration.set()

    assert cleanup_started.wait(1)
    assert cancel_finished.wait(0.05) is False
    cleanup_release.set()
    assert cancel_finished.wait(1)
    cancel_thread.join(timeout=1)

    assert coordinator.take_result() is None


def test_candidate_created_concurrently_with_cancel_is_closed_once():
    candidate_created = threading.Event()
    allow_return = threading.Event()
    candidate = Candidate()

    def startup_job(_cancel_event, _record_timing):
        candidate_created.set()
        allow_return.wait(2)
        return candidate, ("default",)

    coordinator = BackendStartupCoordinator(startup_job, RecordingLogger())
    coordinator.start()
    assert candidate_created.wait(1)

    cancelled = threading.Event()

    def cancel():
        coordinator.cancel()
        cancelled.set()

    cancel_thread = threading.Thread(target=cancel)
    cancel_thread.start()
    allow_return.set()
    assert cancelled.wait(2)
    cancel_thread.join(timeout=1)

    assert candidate.close_calls == 1
    assert coordinator.take_result() is None


def test_result_requires_exactly_one_of_candidate_or_unavailable_reason():
    candidate = Candidate()
    result = BackendStartupResult(candidate, ("default",), None, {})
    assert result.candidate is candidate

    for values in (
        (None, None),
        (candidate, "unavailable"),
    ):
        try:
            BackendStartupResult(values[0], (), values[1], {})
        except ValueError:
            pass
        else:
            raise AssertionError("result must contain exactly one outcome")


def test_cancel_after_result_transfer_leaves_backend_manager_in_control_of_cleanup():
    class LiveBackend:
        def __init__(self):
            self.shutdown_calls = 0

        def shutdown(self):
            self.shutdown_calls += 1

    backend = LiveBackend()
    manager = BackendManager(
        "Piper", "voice", object(), lambda: None, lambda *_args: None
    )
    cleanup_calls = []

    def startup_job(cancel_event, _record_timing):
        cancel_event.register_cancel_cleanup(
            lambda: (cleanup_calls.append(True), backend.shutdown())
        )
        return BackendCandidate(
            "Chatterbox Nano", "default", backend, backend.shutdown
        ), ()

    coordinator = BackendStartupCoordinator(startup_job, RecordingLogger())
    coordinator.start()
    result = wait_until_result(coordinator)
    manager.commit(result.candidate)
    leased_backend, release = manager.acquire()
    assert leased_backend is backend

    coordinator.cancel()
    manager.shutdown()

    assert cleanup_calls == []
    assert backend.shutdown_calls == 0
    release()
    assert backend.shutdown_calls == 1


def test_cancel_disposes_a_result_that_has_not_been_transferred():
    candidate = Candidate()
    cleanup_calls = []

    def startup_job(cancel_event, _record_timing):
        cancel_event.register_cancel_cleanup(lambda: cleanup_calls.append(True))
        return candidate, ("default",)

    coordinator = BackendStartupCoordinator(startup_job, RecordingLogger())
    coordinator.start()
    deadline = time.monotonic() + 2
    while coordinator._results.empty() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert not coordinator._results.empty()

    coordinator.cancel()

    assert candidate.close_calls == 1
    assert cleanup_calls == [True]
    assert coordinator.take_result() is None


def test_failed_startup_keeps_registered_cleanup_until_cancellation():
    cleanup_calls = []

    def startup_job(cancel_event, _record_timing):
        cancel_event.register_cancel_cleanup(lambda: cleanup_calls.append(True))
        raise RuntimeError("startup failed")

    coordinator = BackendStartupCoordinator(startup_job, RecordingLogger())
    coordinator.start()
    result = wait_until_result(coordinator)
    assert result.candidate is None

    coordinator.cancel()

    assert cleanup_calls == [True]
