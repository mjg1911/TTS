import ctypes

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
