import threading

from piper.windows_tray.single_instance import InstanceRole, SingleInstance


class FakeKernel:
    def __init__(self, already_exists: bool) -> None:
        self.already_exists = already_exists
        self.signals = 0
        self._event = threading.Event()
        self.wait_started = threading.Event()
        self.released: list[int] = []
        self.closed: list[int] = []

    def create_event(self, name: str) -> int:
        return 10

    def create_mutex(self, name: str) -> tuple[int, bool]:
        return 20, self.already_exists

    def signal_event(self, handle: int) -> None:
        self.signals += 1
        self._event.set()

    def wait_event(self, handle: int) -> None:
        self.wait_started.set()
        self._event.wait()
        self._event.clear()

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
    monkeypatch.setattr("ctypes.WinDLL", lambda name, use_last_error: kernel32)

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
