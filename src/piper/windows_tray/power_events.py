"""Windows power-broadcast listener for the tray application."""

import ctypes
import logging
import threading
from typing import Callable, Optional


WM_POWERBROADCAST = 0x0218
WM_CLOSE = 0x0010
WM_DESTROY = 0x0002

PBT_APMSUSPEND = 0x0004
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMEAUTOMATIC = 0x0012

_LOGGER = logging.getLogger(__name__)


def is_resume_event(code: int) -> bool:
    return code == PBT_APMRESUMEAUTOMATIC


class _Win32PowerApi:
    def __init__(self) -> None:
        from ctypes import wintypes

        self._wintypes = wintypes
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        self._WNDPROC = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t,
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", self._WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HCURSOR),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        class MSG(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM),
                ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD),
                ("pt", wintypes.POINT),
            ]

        self._WNDCLASSW = WNDCLASSW
        self._MSG = MSG
        self._wndproc = None
        self._class_name: Optional[str] = None
        self._hinstance = None

        self._kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self._kernel32.GetModuleHandleW.restype = wintypes.HMODULE

        self._user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
        self._user32.RegisterClassW.restype = wintypes.ATOM

        self._user32.CreateWindowExW.argtypes = [
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            wintypes.HMENU,
            wintypes.HINSTANCE,
            wintypes.LPVOID,
        ]
        self._user32.CreateWindowExW.restype = wintypes.HWND

        self._user32.DefWindowProcW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self._user32.DefWindowProcW.restype = ctypes.c_ssize_t

        self._user32.PostQuitMessage.argtypes = [ctypes.c_int]
        self._user32.PostQuitMessage.restype = None

        self._user32.PostMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self._user32.PostMessageW.restype = wintypes.BOOL

        self._user32.GetMessageW.argtypes = [
            ctypes.POINTER(MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
        ]
        self._user32.GetMessageW.restype = ctypes.c_int

        self._user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
        self._user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]

        self._user32.UnregisterClassW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.HINSTANCE,
        ]
        self._user32.UnregisterClassW.restype = wintypes.BOOL

    def create_hidden_window(self, on_resume: Callable[[], None]) -> int:
        class_name = f"PiperTrayPowerBroadcast_{id(self):x}"
        hinstance = self._kernel32.GetModuleHandleW(None)
        if not hinstance:
            raise ctypes.WinError(ctypes.get_last_error())

        @self._WNDPROC
        def wndproc(hwnd, message, w_param, l_param):
            if message == WM_POWERBROADCAST and is_resume_event(int(w_param)):
                on_resume()
                return 1

            if message == WM_DESTROY:
                self._user32.PostQuitMessage(0)
                return 0

            return self._user32.DefWindowProcW(
                hwnd,
                message,
                w_param,
                l_param,
            )

        window_class = self._WNDCLASSW()
        window_class.lpfnWndProc = wndproc
        window_class.hInstance = hinstance
        window_class.lpszClassName = class_name

        if not self._user32.RegisterClassW(ctypes.byref(window_class)):
            raise ctypes.WinError(ctypes.get_last_error())

        hwnd = self._user32.CreateWindowExW(
            0,
            class_name,
            "PiperTrayPowerBroadcast",
            0,
            0,
            0,
            0,
            0,
            None,
            None,
            hinstance,
            None,
        )
        if not hwnd:
            error = ctypes.WinError(ctypes.get_last_error())
            self._user32.UnregisterClassW(class_name, hinstance)
            raise error

        self._wndproc = wndproc
        self._class_name = class_name
        self._hinstance = hinstance
        return int(hwnd)

    def message_loop(self) -> None:
        msg = self._MSG()
        try:
            while True:
                result = self._user32.GetMessageW(
                    ctypes.byref(msg),
                    None,
                    0,
                    0,
                )
                if result == 0:
                    return
                if result < 0:
                    raise ctypes.WinError(ctypes.get_last_error())

                self._user32.TranslateMessage(ctypes.byref(msg))
                self._user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            if self._class_name is not None and self._hinstance is not None:
                self._user32.UnregisterClassW(
                    self._class_name,
                    self._hinstance,
                )
            self._class_name = None
            self._hinstance = None
            self._wndproc = None

    def post_close(self, hwnd: int) -> None:
        if not self._user32.PostMessageW(hwnd, WM_CLOSE, 0, 0):
            raise ctypes.WinError(ctypes.get_last_error())


class PowerBroadcastListener:
    def __init__(self, api=None) -> None:
        self._api = api if api is not None else _Win32PowerApi()
        self._thread: Optional[threading.Thread] = None
        self._hwnd: Optional[int] = None
        self._ready = threading.Event()
        self._startup_error: Optional[BaseException] = None
        self._lock = threading.RLock()

    def start(self, on_resume: Callable[[], None]) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return

            self._ready.clear()
            self._startup_error = None
            self._hwnd = None

            def run() -> None:
                try:
                    hwnd = self._api.create_hidden_window(on_resume)
                    with self._lock:
                        self._hwnd = hwnd
                    self._ready.set()
                    self._api.message_loop()
                except BaseException as error:
                    if not self._ready.is_set():
                        self._startup_error = error
                        self._ready.set()
                    else:
                        _LOGGER.error(
                            "power listener stopped exception_type=%s",
                            type(error).__name__,
                        )

            self._thread = threading.Thread(
                target=run,
                name="piper-power-events",
                daemon=True,
            )
            self._thread.start()

        if not self._ready.wait(timeout=2.0):
            raise OSError("power listener did not initialize")

        if self._startup_error is not None:
            error = self._startup_error
            self.stop()
            raise error

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            hwnd = self._hwnd

            if thread is None:
                return

            if thread.is_alive() and hwnd is not None:
                self._api.post_close(hwnd)

        if thread is not threading.current_thread():
            thread.join(timeout=1.0)

        if thread.is_alive():
            raise OSError("power listener did not stop")

        with self._lock:
            if self._thread is thread:
                self._thread = None
                self._hwnd = None
