import ctypes
from ctypes import wintypes
from unittest.mock import Mock

import pytest

from piper.windows_tray.clipboard import Win32Clipboard, _INPUT


class ClipboardMemory:
    """Model Win32 ownership: EmptyClipboard invalidates old handles."""

    def __init__(self, formats):
        self.memory = {}
        self.formats = {}
        self.next_handle = 100
        self.freed = []
        for format_id, data in formats.items():
            handle = self.alloc(2, len(data))
            ctypes.memmove(self.lock(handle), data, len(data))
            self.formats[format_id] = handle
        self.user32 = Mock()
        self.kernel32 = Mock()
        self.user32.OpenClipboard.return_value = True
        self.user32.CreateWindowExW.return_value = 42
        self.user32.EnumClipboardFormats.side_effect = self.enum
        self.user32.GetClipboardData.side_effect = self.formats.get
        self.user32.EmptyClipboard.side_effect = self.empty
        self.user32.SetClipboardData.side_effect = self.set_data
        self.kernel32.GlobalSize.side_effect = lambda handle: len(self.memory[handle])
        self.kernel32.GlobalLock.side_effect = self.lock
        self.kernel32.GlobalAlloc.side_effect = self.alloc
        self.kernel32.GlobalFree.side_effect = self.free
        self.adapter = Win32Clipboard()
        self.adapter._user32 = self.user32
        self.adapter._kernel32 = self.kernel32

    def alloc(self, _flags, size):
        self.next_handle += 1
        self.memory[self.next_handle] = ctypes.create_string_buffer(size)
        return self.next_handle

    def lock(self, handle):
        return ctypes.addressof(self.memory[handle])

    def free(self, handle):
        self.freed.append(handle)
        del self.memory[handle]
        return None

    def enum(self, previous):
        formats = list(self.formats)
        index = formats.index(previous) + 1 if previous else 0
        return formats[index] if index < len(formats) else 0

    def empty(self):
        for handle in self.formats.values():
            self.free(handle)
        self.formats.clear()
        return True

    def set_data(self, format_id, handle):
        self.formats[format_id] = handle
        return handle


@pytest.mark.parametrize(
    "formats",
    [
        {},
        {13: "hello\x00".encode("utf-16-le")},
        {13: "hello\x00".encode("utf-16-le"), 49152: b"<b>hello</b>\x00"},
        {15: b"file-list-data\x00"},
    ],
)
def test_snapshot_restore_preserves_clipboard_formats(formats):
    memory = ClipboardMemory(formats)
    snapshot = memory.adapter.snapshot()
    memory.empty()
    handle = memory.alloc(2, 4)
    memory.set_data(13, handle)

    memory.adapter.restore(snapshot)

    restored = {
        key: bytes(memory.memory[handle]) for key, handle in memory.formats.items()
    }
    assert restored == formats
    memory.user32.OpenClipboard.assert_called_with(42)
    memory.user32.CloseClipboard.assert_called()
    memory.user32.DestroyWindow.assert_called_with(42)


def test_snapshot_failure_closes_clipboard_without_emptying():
    memory = ClipboardMemory({13: b"text"})
    memory.kernel32.GlobalLock.return_value = None
    memory.kernel32.GlobalLock.side_effect = None

    with pytest.raises(OSError):
        memory.adapter.snapshot()

    memory.user32.CloseClipboard.assert_called_once()
    memory.user32.EmptyClipboard.assert_not_called()


def test_restore_set_failure_frees_untransferred_memory():
    memory = ClipboardMemory({})
    memory.user32.SetClipboardData.side_effect = None
    memory.user32.SetClipboardData.return_value = None

    with pytest.raises(OSError):
        memory.adapter.restore({13: b"text"})

    assert not memory.memory
    memory.user32.CloseClipboard.assert_called_once()
    memory.user32.DestroyWindow.assert_called_once_with(42)


def test_restore_allocation_failure_does_not_empty_clipboard():
    memory = ClipboardMemory({13: b"original"})
    memory.kernel32.GlobalAlloc.side_effect = None
    memory.kernel32.GlobalAlloc.return_value = None

    with pytest.raises(OSError):
        memory.adapter.restore({13: b"saved"})

    memory.user32.EmptyClipboard.assert_not_called()


def test_snapshot_refuses_handle_formats_before_copy_can_destroy_them():
    memory = ClipboardMemory({2: b"bitmap-handle"})

    with pytest.raises(OSError):
        memory.adapter.snapshot()

    memory.user32.EmptyClipboard.assert_not_called()


@pytest.mark.parametrize("image_format", [8, 17])
def test_snapshot_restore_preserves_bitmap_through_dib(image_format):
    dib = b"saved bitmap pixels"
    memory = ClipboardMemory({2: b"gdi handle", 9: b"palette", image_format: dib})

    snapshot = memory.adapter.snapshot()
    memory.empty()
    memory.adapter.restore(snapshot)

    assert snapshot == {image_format: dib}
    assert bytes(memory.memory[memory.formats[image_format]]) == dib
    assert 2 not in memory.formats


def test_snapshot_refuses_bitmap_without_readable_dib():
    memory = ClipboardMemory({2: b"gdi handle", 8: b"pixels"})
    memory.user32.GetClipboardData.side_effect = lambda _format: None

    with pytest.raises(OSError):
        memory.adapter.snapshot()

    memory.user32.EmptyClipboard.assert_not_called()


def test_snapshot_restore_preserves_registered_empty_marker():
    memory = ClipboardMemory({49152: b""})

    def marker_data(_format):
        ctypes.set_last_error(0)
        return None

    memory.user32.GetClipboardData.side_effect = marker_data

    def marker_name(_format, buffer, _size):
        buffer.value = "ExcludeClipboardContentFromMonitorProcessing"
        return len(buffer.value)

    memory.user32.GetClipboardFormatNameW.side_effect = marker_name

    snapshot = memory.adapter.snapshot()
    memory.empty()
    memory.adapter.restore(snapshot)

    assert snapshot == {49152: b""}
    assert bytes(memory.memory[memory.formats[49152]]) == b"\x00"


def test_snapshot_refuses_unrendered_registered_data_without_error():
    memory = ClipboardMemory({49152: b"saved"})
    memory.user32.GetClipboardData.side_effect = lambda _format: None
    memory.user32.GetClipboardFormatNameW.return_value = 0

    with pytest.raises(OSError):
        memory.adapter.snapshot()

    memory.user32.EmptyClipboard.assert_not_called()


def test_snapshot_restore_preserves_zero_size_memory():
    memory = ClipboardMemory({49152: b""})

    snapshot = memory.adapter.snapshot()
    memory.empty()
    memory.adapter.restore(snapshot)

    assert snapshot == {49152: b""}
    assert bytes(memory.memory[memory.formats[49152]]) == b"\x00"


def test_snapshot_does_not_treat_failed_registered_data_as_empty():
    memory = ClipboardMemory({49152: b"saved"})

    def failed_data(_format):
        ctypes.set_last_error(5)
        return None

    memory.user32.GetClipboardData.side_effect = failed_data

    with pytest.raises(OSError):
        memory.adapter.snapshot()

    memory.user32.EmptyClipboard.assert_not_called()


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
    assert kernel32.GlobalAlloc.restype is ctypes.c_void_p
    assert kernel32.GlobalSize.restype is ctypes.c_size_t
    assert kernel32.GlobalFree.restype is ctypes.c_void_p
    assert user32.SetClipboardData.restype is ctypes.c_void_p
    assert user32.CreateWindowExW.restype is wintypes.HWND
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
