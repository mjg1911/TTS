import ctypes
from ctypes import wintypes

from piper.windows_tray.clipboard import Win32Clipboard, _INPUT


def test_input_structure_matches_win32_size():
    expected_size = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28

    assert ctypes.sizeof(_INPUT) == expected_size


def test_clipboard_pointer_functions_use_pointer_return_types(monkeypatch):
    class FakeFunction:
        def __init__(self):
            self.argtypes = None
            self.restype = None

    class FakeLibrary:
        def __getattr__(self, _name):
            function = FakeFunction()
            setattr(self, _name, function)
            return function

    user32 = FakeLibrary()
    kernel32 = FakeLibrary()
    libraries = {"user32": user32, "kernel32": kernel32}
    monkeypatch.setattr(ctypes, "WinDLL", lambda name, use_last_error: libraries[name])

    Win32Clipboard()._load_libraries()

    assert user32.GetClipboardData.restype is ctypes.c_void_p
    assert kernel32.GlobalLock.restype is ctypes.c_void_p
    assert user32.SendInput.argtypes == [
        wintypes.UINT,
        ctypes.POINTER(_INPUT),
        ctypes.c_int,
    ]
    assert user32.SendInput.restype is wintypes.UINT


def test_send_ctrl_c_passes_a_pointer_to_the_first_input(monkeypatch):
    class FakeFunction:
        def __init__(self, result=0):
            self.argtypes = None
            self.restype = None
            self.calls = []
            self.result = result

        def __call__(self, *args):
            self.calls.append(args)
            return self.result

    class FakeLibrary:
        def __init__(self):
            self.SendInput = FakeFunction(result=4)

        def __getattr__(self, _name):
            function = FakeFunction()
            setattr(self, _name, function)
            return function

    user32 = FakeLibrary()
    kernel32 = FakeLibrary()
    libraries = {"user32": user32, "kernel32": kernel32}
    monkeypatch.setattr(ctypes, "WinDLL", lambda name, use_last_error: libraries[name])

    Win32Clipboard().send_ctrl_c()

    assert user32.SendInput.calls[0][0] == 4
    assert isinstance(user32.SendInput.calls[0][1], ctypes.POINTER(_INPUT))
