"""Small, lazy Win32 adapters used by selection capture."""

import ctypes
from ctypes import wintypes
from typing import Any, Dict, Optional


CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_C = 0x43
# These formats contain GDI handles or private pointers rather than HGLOBAL
# bytes. Refuse capture rather than silently discarding data we cannot restore.
_HANDLE_FORMATS = {2, 3, 9, 14, 0x80, 0x82, 0x83, 0x8E}


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", _MOUSEINPUT),
        ("ki", _KEYBDINPUT),
        ("hi", _HARDWAREINPUT),
    ]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUT_UNION)]


class Win32Clipboard:
    """Lazy user32/kernel32 clipboard and input adapter."""

    def __init__(self) -> None:
        self._user32: Optional[Any] = None
        self._kernel32: Optional[Any] = None

    def _load_libraries(self) -> None:
        if self._user32 is not None:
            return
        if not hasattr(ctypes, "WinDLL"):
            raise OSError("Win32 clipboard is only available on Windows")
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._user32.OpenClipboard.argtypes = [wintypes.HWND]
        self._user32.OpenClipboard.restype = wintypes.BOOL
        self._user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
        self._user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
        self._user32.GetClipboardData.argtypes = [wintypes.UINT]
        self._user32.GetClipboardData.restype = ctypes.c_void_p
        self._user32.CloseClipboard.argtypes = []
        self._user32.CloseClipboard.restype = wintypes.BOOL
        self._user32.EnumClipboardFormats.argtypes = [wintypes.UINT]
        self._user32.EnumClipboardFormats.restype = wintypes.UINT
        self._user32.EmptyClipboard.argtypes = []
        self._user32.EmptyClipboard.restype = wintypes.BOOL
        self._user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
        self._user32.SetClipboardData.restype = ctypes.c_void_p
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
            ctypes.c_void_p,
        ]
        self._user32.CreateWindowExW.restype = wintypes.HWND
        self._user32.DestroyWindow.argtypes = [wintypes.HWND]
        self._user32.DestroyWindow.restype = wintypes.BOOL
        self._kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
        self._kernel32.GlobalSize.restype = ctypes.c_size_t
        self._kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        self._kernel32.GlobalAlloc.restype = ctypes.c_void_p
        self._kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
        self._kernel32.GlobalFree.restype = ctypes.c_void_p
        self._kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        self._kernel32.GlobalLock.restype = ctypes.c_void_p
        self._kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        self._kernel32.GlobalUnlock.restype = wintypes.BOOL
        self._user32.SendInput.argtypes = [
            wintypes.UINT,
            ctypes.POINTER(_INPUT),
            ctypes.c_int,
        ]
        self._user32.SendInput.restype = wintypes.UINT

    def sequence_number(self) -> int:
        self._load_libraries()
        assert self._user32 is not None
        sequence = self._user32.GetClipboardSequenceNumber()
        if not sequence:
            error = ctypes.get_last_error()
            if error:
                raise OSError(error, "GetClipboardSequenceNumber failed")
        return int(sequence)

    def read_text(self) -> str:
        self._load_libraries()
        assert self._user32 is not None
        assert self._kernel32 is not None

        if not self._user32.OpenClipboard(None):
            raise _last_error("OpenClipboard failed")
        try:
            if not self._user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                return ""
            handle = self._user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                raise _last_error("GetClipboardData failed")
            pointer = self._kernel32.GlobalLock(handle)
            if not pointer:
                raise _last_error("GlobalLock failed")
            try:
                return ctypes.wstring_at(pointer)
            finally:
                self._kernel32.GlobalUnlock(handle)
        finally:
            self._user32.CloseClipboard()

    def snapshot(self) -> Dict[int, bytes]:
        """Copy clipboard memory, never retaining handles invalidated by Ctrl+C."""
        self._load_libraries()
        assert self._user32 is not None
        assert self._kernel32 is not None
        if not self._user32.OpenClipboard(None):
            raise _last_error("OpenClipboard failed")
        try:
            snapshot = {}
            format_id = 0
            while True:
                ctypes.set_last_error(0)
                format_id = self._user32.EnumClipboardFormats(format_id)
                if not format_id:
                    if ctypes.get_last_error():
                        raise _last_error("EnumClipboardFormats failed")
                    return snapshot
                if format_id in _HANDLE_FORMATS or 0x200 <= format_id <= 0x3FF:
                    raise OSError("Clipboard format cannot be safely preserved")
                handle = self._user32.GetClipboardData(format_id)
                if not handle:
                    raise _last_error("GetClipboardData failed")
                size = self._kernel32.GlobalSize(handle)
                if not size:
                    raise _last_error("GlobalSize failed")
                pointer = self._kernel32.GlobalLock(handle)
                if not pointer:
                    raise _last_error("GlobalLock failed")
                try:
                    snapshot[format_id] = ctypes.string_at(pointer, size)
                finally:
                    self._kernel32.GlobalUnlock(handle)
        finally:
            self._user32.CloseClipboard()

    def restore(self, snapshot: Dict[int, bytes]) -> None:
        """Restore saved formats, transferring new memory handles to Windows."""
        self._load_libraries()
        assert self._user32 is not None
        assert self._kernel32 is not None
        handles = {}
        window = None
        try:
            # Allocate everything before clearing the clipboard. Allocation
            # failures must not destroy its current contents.
            for format_id, data in snapshot.items():
                handle = self._kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
                if not handle:
                    raise _last_error("GlobalAlloc failed")
                handles[format_id] = handle
                pointer = self._kernel32.GlobalLock(handle)
                if not pointer:
                    raise _last_error("GlobalLock failed")
                try:
                    ctypes.memmove(pointer, data, len(data))
                finally:
                    self._kernel32.GlobalUnlock(handle)

            # EmptyClipboard requires an owner window for SetClipboardData.
            # A message-only STATIC window belongs to this capture thread.
            window = self._user32.CreateWindowExW(
                0, "STATIC", "", 0, 0, 0, 0, 0, -3, None, None, None
            )
            if not window:
                raise _last_error("CreateWindowExW failed")
            if not self._user32.OpenClipboard(window):
                raise _last_error("OpenClipboard failed")
            try:
                if not self._user32.EmptyClipboard():
                    raise _last_error("EmptyClipboard failed")
                for format_id in list(handles):
                    if not self._user32.SetClipboardData(format_id, handles[format_id]):
                        raise _last_error("SetClipboardData failed")
                    del handles[format_id]  # Windows now owns this allocation.
            finally:
                self._user32.CloseClipboard()
        finally:
            for handle in handles.values():
                self._kernel32.GlobalFree(handle)
            if window:
                self._user32.DestroyWindow(window)

    def send_ctrl_c(self) -> None:
        self._load_libraries()
        assert self._user32 is not None
        inputs = (_INPUT * 4)(
            _keyboard_input(VK_CONTROL, 0),
            _keyboard_input(VK_C, 0),
            _keyboard_input(VK_C, KEYEVENTF_KEYUP),
            _keyboard_input(VK_CONTROL, KEYEVENTF_KEYUP),
        )
        input_pointer = ctypes.cast(inputs, ctypes.POINTER(_INPUT))
        sent = self._user32.SendInput(4, input_pointer, ctypes.sizeof(_INPUT))
        if sent != 4:
            raise _last_error("SendInput failed")


ClipboardAdapter = Win32Clipboard


def _keyboard_input(vk: int, flags: int) -> _INPUT:
    value = _INPUT()
    value.type = INPUT_KEYBOARD
    value.ki = _KEYBDINPUT(vk, 0, flags, 0, 0)
    return value


def _last_error(message: str) -> OSError:
    error = ctypes.get_last_error()
    return OSError(error, message)


def send_ctrl_c() -> None:
    """Send Ctrl+C through a lazily loaded Win32 input adapter."""

    Win32Clipboard().send_ctrl_c()
