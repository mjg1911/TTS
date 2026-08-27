from typing import Iterable, List, Union

import pytest

from piper.windows_tray.capture import CaptureStatus, SelectionCapture


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeClipboard:
    def __init__(
        self,
        sequences: Iterable[int],
        reads: Iterable[Union[str, Exception]],
    ) -> None:
        self.sequences = iter(sequences)
        self.reads = iter(reads)

    def sequence_number(self) -> int:
        return next(self.sequences)

    def read_text(self) -> str:
        value = next(self.reads)
        if isinstance(value, Exception):
            raise value
        return value


def make_capture(clipboard: FakeClipboard, clock: FakeClock) -> SelectionCapture:
    return SelectionCapture(
        clipboard=clipboard,
        send_copy=lambda: None,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )


def test_unchanged_clipboard_never_returns_preexisting_text() -> None:
    clock = FakeClock()
    clipboard = FakeClipboard([7, 7, 7, 7], ["old text"])

    result = make_capture(clipboard, clock).capture(timeout_s=0.10, poll_s=0.05)

    assert result.status is CaptureStatus.TIMEOUT
    assert result.text is None


def test_changed_sequence_retries_until_non_whitespace_text() -> None:
    clock = FakeClock()
    clipboard = FakeClipboard([7, 8, 8], ["   ", "new text"])

    result = make_capture(clipboard, clock).capture(timeout_s=0.20, poll_s=0.05)

    assert result.status is CaptureStatus.SUCCESS
    assert result.text == "new text"


def test_changed_sequence_with_only_whitespace_returns_empty() -> None:
    clock = FakeClock()
    clipboard = FakeClipboard([3, 4, 4, 4], [" \t\n", ""])

    result = make_capture(clipboard, clock).capture(timeout_s=0.10, poll_s=0.05)

    assert result.status is CaptureStatus.EMPTY
    assert result.text is None


def test_temporary_clipboard_error_is_retried() -> None:
    clock = FakeClock()
    clipboard = FakeClipboard([10, 11, 11], [OSError("busy"), "fresh text"])

    result = make_capture(clipboard, clock).capture(timeout_s=0.20, poll_s=0.05)

    assert result.status is CaptureStatus.SUCCESS
    assert result.text == "fresh text"


def test_clipboard_error_until_timeout_returns_access_error() -> None:
    clock = FakeClock()
    clipboard = FakeClipboard([10, 11, 11, 11], [OSError("busy")])

    result = make_capture(clipboard, clock).capture(timeout_s=0.10, poll_s=0.05)

    assert result.status is CaptureStatus.ACCESS_ERROR
    assert result.text is None
    assert result.detail == "busy"


def test_send_copy_error_returns_access_error_without_polling() -> None:
    clock = FakeClock()
    clipboard = FakeClipboard([2], [])

    capture = SelectionCapture(
        clipboard=clipboard,
        send_copy=lambda: (_ for _ in ()).throw(OSError("SendInput failed")),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    result = capture.capture()

    assert result.status is CaptureStatus.ACCESS_ERROR
    assert result.detail == "SendInput failed"


def test_capture_sends_ctrl_c_after_reading_sequence() -> None:
    events: List[str] = []

    class OrderedClipboard(FakeClipboard):
        def sequence_number(self) -> int:
            events.append("sequence")
            return super().sequence_number()

    clock = FakeClock()
    clipboard = OrderedClipboard([1, 2], ["text"])
    capture = SelectionCapture(
        clipboard=clipboard,
        send_copy=lambda: events.append("copy"),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    result = capture.capture(timeout_s=0.10, poll_s=0.05)

    assert result.status is CaptureStatus.SUCCESS
    assert events[:2] == ["sequence", "copy"]


def test_capture_waits_for_hotkey_modifiers_before_copying() -> None:
    clock = FakeClock()
    clipboard = FakeClipboard([1, 2], ["text"])

    result = make_capture(clipboard, clock).capture(timeout_s=0.10, poll_s=0.05)

    assert result.status is CaptureStatus.SUCCESS
    assert clock.now >= 0.15


@pytest.mark.parametrize("value", ["\x00", "\x00\x00"])
def test_null_only_clipboard_text_is_not_success(value: str) -> None:
    clock = FakeClock()
    clipboard = FakeClipboard([1, 2, 2], [value])

    result = make_capture(clipboard, clock).capture(timeout_s=0.10, poll_s=0.05)

    assert result.status is CaptureStatus.EMPTY
