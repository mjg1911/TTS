import threading
import time

from piper.windows_tray.kokoro_verification import KokoroVerificationCoordinator


class RecordingLogger:
    def __init__(self):
        self.warnings = []

    def warning(self, message, *args):
        self.warnings.append(message % args if args else message)


def wait_for_result(coordinator):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        result = coordinator.take_result()
        if result is not None:
            return result
        time.sleep(0.005)
    raise AssertionError("verification result was not delivered")


def test_success_runs_off_calling_thread_and_returns_success_message():
    calling_thread = threading.get_ident()
    worker_threads = []

    def verify():
        worker_threads.append(threading.get_ident())

    coordinator = KokoroVerificationCoordinator(verify, RecordingLogger())

    assert coordinator.start() is True
    result = wait_for_result(coordinator)

    assert worker_threads == [worker_threads[0]]
    assert worker_threads[0] != calling_thread
    assert result.succeeded is True
    assert result.message == "Kokoro files verified successfully."


def test_duplicate_start_is_rejected_while_verification_is_running():
    entered = threading.Event()
    release = threading.Event()

    def verify():
        entered.set()
        release.wait(2)

    coordinator = KokoroVerificationCoordinator(verify, RecordingLogger())

    assert coordinator.start() is True
    assert entered.wait(1)
    assert coordinator.start() is False
    release.set()
    assert wait_for_result(coordinator).succeeded is True


def test_failure_is_sanitized_and_logged_by_exception_type():
    logger = RecordingLogger()

    def verify():
        raise ValueError(r"C:\private\Kokoro\model.pth hash mismatch")

    coordinator = KokoroVerificationCoordinator(verify, logger)

    assert coordinator.start() is True
    result = wait_for_result(coordinator)

    assert result.succeeded is False
    assert result.message == (
        "Kokoro verification failed. Some installed files are missing or corrupted."
    )
    assert logger.warnings == [
        "Kokoro integrity verification failed error_type=ValueError"
    ]
    assert "private" not in result.message
