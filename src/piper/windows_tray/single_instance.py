"""Single-instance coordination for the Windows tray application."""

from enum import Enum, auto
import ctypes
from ctypes import wintypes
import logging
import threading
from typing import Callable, Optional, Tuple


MUTEX_NAME = r"Local\PiperTray.Singleton.v1"
ACTIVATION_EVENT_NAME = r"Local\PiperTray.Activate.v1"
ERROR_ALREADY_EXISTS = 183
INFINITE = 0xFFFFFFFF
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258
WAIT_FAILED = 0xFFFFFFFF
WATCHER_WAIT_MS = 100

_LOGGER = logging.getLogger("piper.windows_tray.single_instance")


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

    def wait_event(self, handle: int, timeout: int = INFINITE) -> int:
        result = self._kernel32.WaitForSingleObject(
            wintypes.HANDLE(handle), timeout
        )
        if result == WAIT_OBJECT_0:
            return result
        if result == WAIT_TIMEOUT:
            return result
        if result == WAIT_FAILED:
            raise ctypes.WinError(ctypes.get_last_error())
        raise RuntimeError("unexpected WaitForSingleObject result: %s" % result)

    def release_mutex(self, handle: int) -> None:
        if not self._kernel32.ReleaseMutex(wintypes.HANDLE(handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def close_handle(self, handle: int) -> None:
        if not self._kernel32.CloseHandle(wintypes.HANDLE(handle)):
            raise ctypes.WinError(ctypes.get_last_error())


class SingleInstance:
    def __init__(self, kernel: Optional[KernelApi] = None) -> None:
        self._kernel = kernel or KernelApi()
        self._event: Optional[int] = None
        self._mutex: Optional[int] = None
        self._owns_mutex = False
        self._state_lock = threading.Lock()
        self._closing = False
        self._closed = threading.Event()
        self._shutdown_requested = threading.Event()
        self._watcher: Optional[threading.Thread] = None

    def acquire(self) -> InstanceRole:
        with self._state_lock:
            if self._closing or self._closed.is_set():
                raise RuntimeError("single instance is closed")
            event = None
            mutex = None
            owns_mutex = False
            try:
                event = self._kernel.create_event(ACTIVATION_EVENT_NAME)
                mutex, already_exists = self._kernel.create_mutex(MUTEX_NAME)
                if already_exists:
                    self._kernel.signal_event(event)
                else:
                    owns_mutex = True
                self._event = event
                self._mutex = mutex
                self._owns_mutex = owns_mutex
                return (
                    InstanceRole.SECONDARY
                    if already_exists
                    else InstanceRole.PRIMARY
                )
            except BaseException:
                self._event = None
                self._mutex = None
                self._owns_mutex = False
                self._cleanup_handles(event, mutex, owns_mutex)
                raise

    def _cleanup_handles(
        self, event: Optional[int], mutex: Optional[int], owns_mutex: bool
    ) -> None:
        if owns_mutex and mutex is not None:
            try:
                self._kernel.release_mutex(mutex)
            except Exception:
                _LOGGER.exception("Could not release Piper tray mutex")
        if event is not None:
            try:
                self._kernel.close_handle(event)
            except Exception:
                _LOGGER.exception("Could not close Piper tray event handle")
        if mutex is not None:
            try:
                self._kernel.close_handle(mutex)
            except Exception:
                _LOGGER.exception("Could not close Piper tray mutex handle")

    def start_activation_watch(self, callback: Callable[[], None]) -> threading.Thread:
        def watch() -> None:
            while True:
                with self._state_lock:
                    event = self._event
                if event is None:
                    return
                try:
                    result = self._kernel.wait_event(event, WATCHER_WAIT_MS)
                except (OSError, RuntimeError) as error:
                    _LOGGER.error("Piper activation wait failed: %s", error)
                    return
                if result == WAIT_TIMEOUT:
                    if self._shutdown_requested.is_set():
                        return
                    continue
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
                if watcher is current:
                    return
                wait_for_close = True
            else:
                wait_for_close = False
                self._closing = True
                self._shutdown_requested.set()
                event, mutex = self._event, self._mutex
                owns_mutex = self._owns_mutex
        if wait_for_close:
            self._closed.wait()
            return

        errors = []
        try:
            if watcher is not None and watcher is not current and event is not None:
                try:
                    self._kernel.signal_event(event)
                except Exception as error:
                    errors.append(error)
                    _LOGGER.exception("Could not wake Piper activation watcher")
                watcher.join()

            with self._state_lock:
                self._event = None
                self._mutex = None
                self._watcher = None
                self._owns_mutex = False
            if owns_mutex and mutex is not None:
                try:
                    self._kernel.release_mutex(mutex)
                except Exception as error:
                    errors.append(error)
                    _LOGGER.exception("Could not release Piper tray mutex")
            if event is not None:
                try:
                    self._kernel.close_handle(event)
                except Exception as error:
                    errors.append(error)
                    _LOGGER.exception("Could not close Piper tray event handle")
            if mutex is not None:
                try:
                    self._kernel.close_handle(mutex)
                except Exception as error:
                    errors.append(error)
                    _LOGGER.exception("Could not close Piper tray mutex handle")
        finally:
            self._closed.set()
        if errors:
            raise errors[0]
