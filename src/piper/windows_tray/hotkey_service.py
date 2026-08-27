"""Windows global hotkey registration and message dispatch."""

import ctypes
import threading
from typing import Any, Callable, Optional, Tuple

from .hotkey import MOD_NOREPEAT, VK_F8


CAPTURE_IDS = (1, 3)
CANCEL_ID = 2
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

Callback = Callable[[], None]


class _Win32HotkeyApi:
    """Small lazily-loaded user32 adapter used by the production manager."""

    def __init__(self) -> None:
        self._user32 = None

    def _load_user32(self) -> Any:
        if self._user32 is None:
            self._user32 = ctypes.WinDLL("user32", use_last_error=True)
            self._user32.RegisterHotKey.argtypes = [
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_uint,
                ctypes.c_uint,
            ]
            self._user32.RegisterHotKey.restype = ctypes.c_int
            self._user32.UnregisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int]
            self._user32.UnregisterHotKey.restype = ctypes.c_int
            self._user32.GetMessageW.argtypes = [
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_uint,
                ctypes.c_uint,
            ]
            self._user32.GetMessageW.restype = ctypes.c_int
            self._user32.PostThreadMessageW.argtypes = [
                ctypes.c_uint,
                ctypes.c_uint,
                ctypes.c_size_t,
                ctypes.c_ssize_t,
            ]
            self._user32.PostThreadMessageW.restype = ctypes.c_int
        return self._user32

    def register(self, hotkey_id: int, modifiers: int, vk: int) -> bool:
        return bool(self._load_user32().RegisterHotKey(None, hotkey_id, modifiers, vk))

    def unregister(self, hotkey_id: int) -> None:
        self._load_user32().UnregisterHotKey(None, hotkey_id)

    def get_message(self) -> Tuple[int, int]:
        class MSG(ctypes.Structure):
            _fields_ = [
                ("hwnd", ctypes.c_void_p),
                ("message", ctypes.c_uint),
                ("wparam", ctypes.c_size_t),
                ("lparam", ctypes.c_ssize_t),
                ("time", ctypes.c_uint),
                ("pt_x", ctypes.c_long),
                ("pt_y", ctypes.c_long),
            ]

        msg = MSG()
        result = self._load_user32().GetMessageW(ctypes.byref(msg), None, 0, 0)
        return result, int(msg.wparam)

    def post_quit(self, thread_id: int) -> bool:
        return bool(self._load_user32().PostThreadMessageW(thread_id, WM_QUIT, 0, 0))


class HotkeyManager:
    def __init__(self, api: Optional[Any] = None) -> None:
        self._api = api if api is not None else _Win32HotkeyApi()
        self._active_capture_id = CAPTURE_IDS[0]
        self.capture_spec = None
        self._on_capture: Optional[Callback] = None
        self._on_cancel: Optional[Callback] = None
        self._message_thread: Optional[threading.Thread] = None
        self._message_thread_id = 0
        self._ready = threading.Event()
        self._registration_error: Optional[BaseException] = None
        self._cancel_registered = False
        self._lock = threading.RLock()

    def _register_capture(self, hotkey_id: int, spec: Any) -> bool:
        return self._api.register(
            hotkey_id, spec.modifiers | MOD_NOREPEAT, spec.vk
        )

    def register_for_test(self, capture_spec: Any) -> None:
        with self._lock:
            if self.capture_spec is not None:
                return
            if not self._register_capture(self._active_capture_id, capture_spec):
                raise OSError("capture hotkey registration failed")
            if not self._cancel_registered:
                if not self._api.register(CANCEL_ID, MOD_NOREPEAT, VK_F8):
                    self._api.unregister(self._active_capture_id)
                    raise OSError("F8 registration failed")
                self._cancel_registered = True
            self.capture_spec = capture_spec

    def rebind(self, candidate: Any) -> bool:
        with self._lock:
            if self.capture_spec is None:
                return False
            inactive = CAPTURE_IDS[1] if self._active_capture_id == CAPTURE_IDS[0] else CAPTURE_IDS[0]
            if not self._register_capture(inactive, candidate):
                return False
            self._api.unregister(self._active_capture_id)
            self._active_capture_id = inactive
            self.capture_spec = candidate
            return True

    def reregister(self) -> bool:
        with self._lock:
            if self.capture_spec is None:
                return False
            for hotkey_id in CAPTURE_IDS:
                self._api.unregister(hotkey_id)
            self._api.unregister(CANCEL_ID)
            self._cancel_registered = False
            if not self._register_capture(self._active_capture_id, self.capture_spec):
                return False
            if not self._api.register(CANCEL_ID, MOD_NOREPEAT, VK_F8):
                self._api.unregister(self._active_capture_id)
                return False
            self._cancel_registered = True
            return True

    def dispatch_message(
        self,
        message: int,
        hotkey_id: int,
        on_capture: Optional[Callback] = None,
        on_cancel: Optional[Callback] = None,
    ) -> bool:
        if message == WM_QUIT:
            return False
        if message != WM_HOTKEY:
            return True
        capture = on_capture if on_capture is not None else self._on_capture
        cancel = on_cancel if on_cancel is not None else self._on_cancel
        if hotkey_id in CAPTURE_IDS and hotkey_id == self._active_capture_id:
            if capture is not None:
                capture()
        elif hotkey_id == CANCEL_ID and cancel is not None:
            cancel()
        return True

    def _message_loop(self) -> None:
        self._message_thread_id = threading.get_native_id()
        capture_spec = self.capture_spec
        self.capture_spec = None
        try:
            self.register_for_test(capture_spec)
        except BaseException as exc:
            self._registration_error = exc
            self._ready.set()
            return
        self._ready.set()
        while True:
            result, hotkey_id = self._api.get_message()
            if result <= 0:
                return
            if not self.dispatch_message(result, hotkey_id):
                return

    def start(self, capture_spec: Any, on_capture: Callback, on_cancel: Callback) -> None:
        with self._lock:
            if self._message_thread is not None and self._message_thread.is_alive():
                self._on_capture = on_capture
                self._on_cancel = on_cancel
                return
            self.capture_spec = capture_spec
            self._on_capture = on_capture
            self._on_cancel = on_cancel
            self._ready.clear()
            self._registration_error = None
            self._message_thread = threading.Thread(
                target=self._message_loop, name="piper-hotkeys", daemon=True
            )
            self._message_thread.start()
        self._ready.wait()
        if self._registration_error is not None:
            error = self._registration_error
            self._message_thread.join(timeout=1.0)
            self._message_thread = None
            self.capture_spec = None
            raise error

    def stop(self) -> None:
        with self._lock:
            for hotkey_id in CAPTURE_IDS:
                self._api.unregister(hotkey_id)
            self._api.unregister(CANCEL_ID)
            self._cancel_registered = False
            self.capture_spec = None
            thread = self._message_thread
            if thread is not None and thread.is_alive():
                self._api.post_quit(self._message_thread_id)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        with self._lock:
            self._message_thread = None
