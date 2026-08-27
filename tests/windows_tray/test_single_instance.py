import threading
import pytest

from piper.windows_tray.single_instance import (
    INFINITE,
    WAIT_OBJECT_0,
    WAIT_TIMEOUT,
    InstanceRole,
    SingleInstance,
)


class FakeKernel:
    def __init__(self, already_exists: bool) -> None:
        self.already_exists = already_exists
        self.signals = 0
        self._event = threading.Event()
        self.wait_started = threading.Event()
        self.events_created = 0
        self.mutexes_created = 0
        self.released: list[int] = []
        self.closed: list[int] = []

    def create_event(self, name: str) -> int:
        self.events_created += 1
        return 10

    def create_mutex(self, name: str) -> tuple[int, bool]:
        self.mutexes_created += 1
        return 20, self.already_exists

    def signal_event(self, handle: int) -> None:
        self.signals += 1
        self._event.set()

    def wait_event(self, handle: int, timeout: int = INFINITE) -> int:
        self.wait_started.set()
        if self._event.wait(timeout / 1000):
            self._event.clear()
            return WAIT_OBJECT_0
        return WAIT_TIMEOUT

    def release_mutex(self, handle: int) -> None:
        self.released.append(handle)

    def close_handle(self, handle: int) -> None:
        self.closed.append(handle)


def test_secondary_signals_existing_instance_and_does_not_own_mutex() -> None:
    kernel = FakeKernel(already_exists=True)
    instance = SingleInstance(kernel)

    assert instance.acquire() is InstanceRole.SECONDARY
    assert kernel.signals == 1
    instance.close()

    assert kernel.released == []
    assert kernel.closed == [10, 20]


def test_primary_owns_mutex_without_signaling_and_releases_handles_on_close() -> None:
    kernel = FakeKernel(already_exists=False)
    instance = SingleInstance(kernel)

    assert instance.acquire() is InstanceRole.PRIMARY
    assert kernel.signals == 0

    instance.close()

    assert kernel.released == [20]
    assert kernel.closed == [10, 20]


def test_activation_watch_invokes_callback_for_signaled_event() -> None:
    kernel = FakeKernel(already_exists=False)
    instance = SingleInstance(kernel)
    callback_called = threading.Event()

    instance.acquire()
    watcher = instance.start_activation_watch(callback_called.set)
    assert kernel.wait_started.wait(timeout=1)

    kernel.signal_event(10)

    assert callback_called.wait(timeout=1)
    instance.close()
    watcher.join(timeout=1)
    assert not watcher.is_alive()


def test_close_wakes_watcher_without_invoking_callback_and_is_idempotent() -> None:
    kernel = FakeKernel(already_exists=False)
    instance = SingleInstance(kernel)
    callback_called = threading.Event()

    instance.acquire()
    watcher = instance.start_activation_watch(callback_called.set)
    assert kernel.wait_started.wait(timeout=1)

    instance.close()
    instance.close()

    watcher.join(timeout=1)
    assert not watcher.is_alive()
    assert not callback_called.is_set()
    assert kernel.released == [20]
    assert kernel.closed == [10, 20]


def test_close_waits_for_watcher_when_set_event_fails() -> None:
    class FailingSignalKernel(FakeKernel):
        def signal_event(self, handle: int) -> None:
            raise OSError("SetEvent failed")

        def close_handle(self, handle: int) -> None:
            assert not watcher.is_alive()
            super().close_handle(handle)

    kernel = FailingSignalKernel(already_exists=False)
    instance = SingleInstance(kernel)
    instance.acquire()
    watcher = instance.start_activation_watch(lambda: None)
    assert kernel.wait_started.wait(timeout=1)

    with pytest.raises(OSError, match="SetEvent failed"):
        instance.close()

    watcher.join(timeout=1)
    assert not watcher.is_alive()
    assert kernel.closed == [10, 20]


def test_close_waits_until_watcher_thread_has_started(monkeypatch) -> None:
    from piper.windows_tray import single_instance

    real_thread = threading.Thread
    start_entered = threading.Event()
    allow_start = threading.Event()
    start_errors: list[BaseException] = []
    close_errors: list[BaseException] = []
    watcher_holder: list[threading.Thread] = []

    class DelayedStartThread(real_thread):
        def start(self) -> None:
            start_entered.set()
            if not allow_start.wait(timeout=1):
                raise AssertionError("test did not release delayed thread start")
            super().start()

    monkeypatch.setattr(single_instance.threading, "Thread", DelayedStartThread)
    kernel = FakeKernel(already_exists=False)
    instance = SingleInstance(kernel)
    instance.acquire()

    def start_watcher() -> None:
        try:
            watcher_holder.append(instance.start_activation_watch(lambda: None))
        except BaseException as error:
            start_errors.append(error)

    starter = real_thread(target=start_watcher)
    starter.start()
    assert start_entered.wait(timeout=1)

    close_attempted = threading.Event()

    def close_instance() -> None:
        close_attempted.set()
        try:
            instance.close()
        except BaseException as error:
            close_errors.append(error)

    closer = real_thread(target=close_instance)
    closer.start()
    assert close_attempted.wait(timeout=1)
    allow_start.set()

    starter.join(timeout=1)
    closer.join(timeout=1)
    assert not starter.is_alive()
    assert not closer.is_alive()
    assert start_errors == []
    assert close_errors == []
    assert watcher_holder and not watcher_holder[0].is_alive()


def test_acquire_rejects_calls_after_close() -> None:
    kernel = FakeKernel(already_exists=False)
    instance = SingleInstance(kernel)
    instance.close()

    try:
        instance.acquire()
    except RuntimeError:
        pass
    else:
        raise AssertionError("acquire() should reject a closed instance")

    assert kernel.events_created == 0
    assert kernel.mutexes_created == 0


class FakeFunction:
    def __init__(self) -> None:
        self.restype = None
        self.argtypes = None


class FakeKernel32:
    def __init__(self) -> None:
        self.CreateEventW = FakeFunction()
        self.CreateMutexW = FakeFunction()
        self.SetEvent = FakeFunction()
        self.WaitForSingleObject = FakeFunction()
        self.ReleaseMutex = FakeFunction()
        self.CloseHandle = FakeFunction()


def test_kernel_api_configures_win32_handle_function_prototypes(monkeypatch) -> None:
    from ctypes import wintypes

    from piper.windows_tray.single_instance import KernelApi

    kernel32 = FakeKernel32()
    monkeypatch.setattr(
        "ctypes.WinDLL", lambda name, use_last_error: kernel32, raising=False
    )

    KernelApi()

    assert kernel32.CreateEventW.restype is wintypes.HANDLE
    assert kernel32.CreateEventW.argtypes == [
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    assert kernel32.CreateMutexW.restype is wintypes.HANDLE
    assert kernel32.CreateMutexW.argtypes == [
        wintypes.LPVOID,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    for function in (
        kernel32.SetEvent,
        kernel32.ReleaseMutex,
        kernel32.CloseHandle,
    ):
        assert function.restype is wintypes.BOOL
        assert function.argtypes == [wintypes.HANDLE]
    assert kernel32.WaitForSingleObject.restype is wintypes.DWORD
    assert kernel32.WaitForSingleObject.argtypes == [
        wintypes.HANDLE,
        wintypes.DWORD,
    ]


class TransactionKernel:
    def __init__(self, mutex_error=None, signal_error=None):
        self.mutex_error = mutex_error
        self.signal_error = signal_error
        self.closed = []
        self.released = []

    def create_event(self, _name):
        return 10

    def create_mutex(self, _name):
        if self.mutex_error:
            raise self.mutex_error
        return 20, True

    def signal_event(self, _handle):
        if self.signal_error:
            raise self.signal_error

    def wait_event(self, _handle, _timeout=INFINITE):
        pass

    def release_mutex(self, handle):
        self.released.append(handle)

    def close_handle(self, handle):
        self.closed.append(handle)


def test_acquire_rolls_back_event_when_mutex_creation_fails() -> None:
    kernel = TransactionKernel(mutex_error=OSError("mutex"))
    instance = SingleInstance(kernel)

    with pytest.raises(OSError):
        instance.acquire()

    assert kernel.closed == [10]


def test_secondary_acquire_rolls_back_both_handles_when_signal_fails() -> None:
    kernel = TransactionKernel(signal_error=OSError("signal"))
    instance = SingleInstance(kernel)

    with pytest.raises(OSError):
        instance.acquire()

    assert kernel.released == []
    assert kernel.closed == [10, 20]


def test_close_raises_cleanup_failure_after_attempting_all_handles() -> None:
    class CleanupFailureKernel(TransactionKernel):
        def __init__(self):
            super().__init__()

        def create_mutex(self, _name):
            return 20, False

        def release_mutex(self, handle):
            self.released.append(handle)
            raise OSError("release")

        def close_handle(self, handle):
            self.closed.append(handle)
            raise OSError("close")

    kernel = CleanupFailureKernel()
    instance = SingleInstance(kernel)
    assert instance.acquire() is InstanceRole.PRIMARY

    with pytest.raises(OSError):
        instance.close()

    assert kernel.released == [20]
    assert kernel.closed == [10, 20]
    instance.close()


class OutcomeFunction:
    def __init__(self, outcome):
        self.outcome = outcome
        self.restype = None
        self.argtypes = None

    def __call__(self, *_args):
        return self.outcome


def test_kernel_api_rejects_wait_failure_and_unexpected_wait_result(monkeypatch) -> None:
    from piper.windows_tray import single_instance

    class Kernel32:
        def __init__(self, outcome):
            self.CreateEventW = OutcomeFunction(1)
            self.CreateMutexW = OutcomeFunction(1)
            self.SetEvent = OutcomeFunction(1)
            self.WaitForSingleObject = OutcomeFunction(outcome)
            self.ReleaseMutex = OutcomeFunction(1)
            self.CloseHandle = OutcomeFunction(1)

    monkeypatch.setattr(
        "ctypes.WinError", lambda _error: OSError("win32"), raising=False
    )
    monkeypatch.setattr(
        "ctypes.WinDLL",
        lambda *_args, **_kwargs: Kernel32(single_instance.WAIT_FAILED),
        raising=False,
    )
    api = single_instance.KernelApi()
    with pytest.raises(OSError):
        api.wait_event(10)

    monkeypatch.setattr(
        "ctypes.WinDLL", lambda *_args, **_kwargs: Kernel32(1), raising=False
    )
    api = single_instance.KernelApi()
    with pytest.raises(RuntimeError):
        api.wait_event(10)


@pytest.mark.parametrize("method", ["ReleaseMutex", "CloseHandle"])
def test_kernel_api_rejects_failed_release_and_close(monkeypatch, method) -> None:
    from piper.windows_tray import single_instance

    class Kernel32:
        def __init__(self):
            self.CreateEventW = OutcomeFunction(1)
            self.CreateMutexW = OutcomeFunction(1)
            self.SetEvent = OutcomeFunction(1)
            self.WaitForSingleObject = OutcomeFunction(single_instance.WAIT_OBJECT_0)
            self.ReleaseMutex = OutcomeFunction(0)
            self.CloseHandle = OutcomeFunction(0)

    monkeypatch.setattr(
        "ctypes.WinError", lambda _error: OSError("win32"), raising=False
    )
    monkeypatch.setattr(
        "ctypes.WinDLL", lambda *_args, **_kwargs: Kernel32(), raising=False
    )
    api = single_instance.KernelApi()

    with pytest.raises(OSError):
        getattr(api, "release_mutex" if method == "ReleaseMutex" else "close_handle")(10)
