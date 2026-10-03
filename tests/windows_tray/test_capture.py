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
        self.contents = "hello"
        self.restored = []

    def snapshot(self):
        return self.contents

    def restore(self, snapshot):
        self.contents = snapshot
        self.restored.append(snapshot)

    def sequence_number(self) -> int:
        return next(self.sequences)

    def read_text(self) -> str:
        value = next(self.reads)
        if isinstance(value, Exception):
            raise value
        self.contents = value
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
    assert clipboard.restored == ["hello"]


def test_changed_sequence_retries_until_non_whitespace_text() -> None:
    clock = FakeClock()
    clipboard = FakeClipboard([7, 8, 8], ["   ", "new text"])

    result = make_capture(clipboard, clock).capture(timeout_s=0.20, poll_s=0.05)

    assert result.status is CaptureStatus.SUCCESS
    assert result.text == "new text"


def test_changed_sequence_with_only_whitespace_returns_empty() -> None:
    clock = FakeClock()
    clipboard = FakeClipboard(
        [3, 4, 4, 4, 4, 4],
        [" \t\n", "", "", ""],
    )

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
    clipboard = FakeClipboard(
        [10, 11, 11, 11, 11, 11],
        [OSError("busy"), OSError("busy"), OSError("busy"), OSError("busy")],
    )

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
    clipboard = FakeClipboard([1, 2, 2, 2, 2], [value, value, value, value])

    result = make_capture(clipboard, clock).capture(timeout_s=0.10, poll_s=0.05)

    assert result.status is CaptureStatus.EMPTY


@pytest.mark.parametrize("original", ["hello", "", b"non-text clipboard"])
def test_capture_restores_clipboard_immediately_after_read(original):
    clock = FakeClock()
    clipboard = FakeClipboard([1, 2], ["read this"])
    clipboard.contents = original

    def copy():
        assert clipboard.contents == original
        clipboard.contents = "read this"

    capture = SelectionCapture(clipboard, copy, clock.monotonic, clock.sleep)
    result = capture.capture()

    assert result.status is CaptureStatus.SUCCESS
    assert result.text == "read this"
    assert clipboard.contents == original
    assert clipboard.restored == [original]
    assert clock.now == 0.15


@pytest.mark.parametrize(
    "reads, status",
    [
        (["", ""], CaptureStatus.EMPTY),
        ([OSError("busy"), OSError("busy")], CaptureStatus.ACCESS_ERROR),
    ],
)
def test_capture_restores_clipboard_on_unsuccessful_read(reads, status):
    clock = FakeClock()
    clipboard = FakeClipboard([1, 2, 2], reads)

    result = make_capture(clipboard, clock).capture(timeout_s=0.10)

    assert result.status is status
    assert clipboard.contents == "hello"
    assert clipboard.restored == ["hello"]


def test_capture_restores_after_copy_raises():
    clock = FakeClock()
    clipboard = FakeClipboard([1], [])

    def copy():
        clipboard.contents = "changed before failure"
        raise OSError("copy failed")

    result = SelectionCapture(clipboard, copy, clock.monotonic, clock.sleep).capture()

    assert result.status is CaptureStatus.ACCESS_ERROR
    assert clipboard.contents == "hello"
    assert clipboard.restored == ["hello"]


def test_snapshot_failure_does_not_send_copy():
    clock = FakeClock()
    clipboard = FakeClipboard([1, 1, 1], [])
    copied = []

    def snapshot():
        raise OSError("snapshot failed")

    clipboard.snapshot = snapshot
    result = SelectionCapture(
        clipboard, lambda: copied.append(True), clock.monotonic, clock.sleep
    ).capture()

    assert result.status is CaptureStatus.ACCESS_ERROR
    assert copied == []
    assert clipboard.restored == []


def test_capture_retries_temporarily_busy_restore():
    clock = FakeClock()
    clipboard = FakeClipboard([1, 2], ["read this"])
    restore = clipboard.restore
    attempts = []

    def busy_restore(snapshot):
        attempts.append(snapshot)
        if len(attempts) == 1:
            raise OSError("busy")
        restore(snapshot)

    clipboard.restore = busy_restore
    result = make_capture(clipboard, clock).capture()

    assert result.status is CaptureStatus.SUCCESS
    assert clipboard.contents == "hello"
    assert attempts == ["hello", "hello"]


def test_restore_failure_is_reported():
    clock = FakeClock()
    clipboard = FakeClipboard([1, 2], ["read this"])

    def restore(_snapshot):
        raise OSError("restore failed")

    clipboard.restore = restore
    result = make_capture(clipboard, clock).capture()

    assert result.status is CaptureStatus.ACCESS_ERROR
    assert result.detail == "restore failed"
