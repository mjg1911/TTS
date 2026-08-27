"""Single-instance coordination for the Windows tray application."""

from enum import Enum, auto
import ctypes
from ctypes import wintypes
import threading
from typing import Callable, Optional, Tuple


MUTEX_NAME = r"Local\PiperTray.Singleton.v1"
ACTIVATION_EVENT_NAME = r"Local\PiperTray.Activate.v1"
ERROR_ALREADY_EXISTS = 183
INFINITE = 0xFFFFFFFF


class InstanceRole(Enum):
    PRIMARY = auto()
    SECONDARY = auto()


class KernelApi:
    def __init__(self) -> None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateEventW.restype = wintypes.HANDLE
        kernel32.CreateEventW.argtypes = [
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = [
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        kernel32.SetEvent.restype = wintypes.BOOL
        kernel32.SetEvent.argtypes = [wintypes.HANDLE]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.ReleaseMutex.restype = wintypes.BOOL
        kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32 = kernel32

    def create_event(self, name: str) -> int:
        handle = self._kernel32.CreateEventW(None, False, False, name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        return int(handle)

    def create_mutex(self, name: str) -> Tuple[int, bool]:
        ctypes.set_last_error(0)
        handle = self._kernel32.CreateMutexW(None, True, name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        return int(handle), ctypes.get_last_error() == ERROR_ALREADY_EXISTS

    def signal_event(self, handle: int) -> None:
        if not self._kernel32.SetEvent(wintypes.HANDLE(handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def wait_event(self, handle: int) -> None:
        self._kernel32.WaitForSingleObject(wintypes.HANDLE(handle), INFINITE)

    def release_mutex(self, handle: int) -> None:
        self._kernel32.ReleaseMutex(wintypes.HANDLE(handle))

    def close_handle(self, handle: int) -> None:
        self._kernel32.CloseHandle(wintypes.HANDLE(handle))


class SingleInstance:
    def __init__(self, kernel: Optional[KernelApi] = None) -> None:
        self._kernel = kernel or KernelApi()
        self._event: Optional[int] = None
        self._mutex: Optional[int] = None
        self._owns_mutex = False
        self._state_lock = threading.Lock()
        self._closing = False
        self._closed = threading.Event()
        self._watcher: Optional[threading.Thread] = None

    def acquire(self) -> InstanceRole:
        self._event = self._kernel.create_event(ACTIVATION_EVENT_NAME)
        self._mutex, already_exists = self._kernel.create_mutex(MUTEX_NAME)
        if already_exists:
            self._kernel.signal_event(self._event)
            return InstanceRole.SECONDARY
        self._owns_mutex = True
        return InstanceRole.PRIMARY

    def start_activation_watch(self, callback: Callable[[], None]) -> threading.Thread:
        def watch() -> None:
            while True:
                with self._state_lock:
                    event = self._event
                if event is None:
                    return
                self._kernel.wait_event(event)
                with self._state_lock:
                    if self._closing or self._event is None:
                        return
                callback()

        with self._state_lock:
            assert self._event is not None
            if self._closing:
                raise RuntimeError("single instance is closed")
            thread = threading.Thread(
                target=watch, name="piper-activation", daemon=True
            )
            self._watcher = thread
        thread.start()
        return thread

    def close(self) -> None:
        current = threading.current_thread()
        with self._state_lock:
            if self._closed.is_set():
                return
            watcher = self._watcher
            if self._closing:
                if watcher is not current:
                    self._closed.wait()
                return
            self._closing = True
            event, mutex = self._event, self._mutex
            owns_mutex = self._owns_mutex

        try:
            if watcher is not None and watcher is not current and event is not None:
                self._kernel.signal_event(event)
                watcher.join()

            with self._state_lock:
                self._event = None
                self._mutex = None
                self._watcher = None
                self._owns_mutex = False
            if owns_mutex and mutex is not None:
                self._kernel.release_mutex(mutex)
            if event is not None:
                self._kernel.close_handle(event)
            if mutex is not None:
                self._kernel.close_handle(mutex)
        finally:
            self._closed.set()
