from types import SimpleNamespace

import pytest

from piper.windows_tray.hotkey import parse_hotkey
from piper.windows_tray.hotkey_service import (
    CANCEL_ID,
    CAPTURE_IDS,
    HotkeyManager,
    WM_HOTKEY,
)
from piper.windows_tray.shortcut_recorder import ShortcutRecorder
from windows_tray.test_hotkey_service import FakeHotkeyApi
from windows_tray.test_shortcut_recorder import Entry, Variable


def test_suspend_unregisters_only_capture_and_queued_capture_is_ignored():
    api = FakeHotkeyApi()
    manager = HotkeyManager(api)
    events = []
    manager.register_for_test(parse_hotkey("alt+backtick"))

    assert manager.suspend_capture() is True
    assert set(api.registered) == {CANCEL_ID}
    manager.dispatch_message(
        WM_HOTKEY, CAPTURE_IDS[0], lambda: events.append("capture")
    )
    manager.dispatch_message(
        WM_HOTKEY,
        CANCEL_ID,
        lambda: events.append("capture"),
        lambda: events.append("cancel"),
    )

    assert events == ["cancel"]


def test_resume_restores_saved_capture_spec_and_is_idempotent():
    api = FakeHotkeyApi()
    manager = HotkeyManager(api)
    spec = parse_hotkey("ctrl+q")
    manager.register_for_test(spec)
    manager.suspend_capture()

    assert manager.resume_capture() is True
    assert manager.resume_capture() is True
    assert manager.capture_spec is spec
    assert api.registered[CAPTURE_IDS[0]][1] == spec.vk
    assert set(api.registered) == {CAPTURE_IDS[0], CANCEL_ID}


def test_failed_resume_returns_false_and_notifies_failure_callback():
    api = FakeHotkeyApi()
    manager = HotkeyManager(api)
    failures = []
    spec = parse_hotkey("ctrl+q")
    manager.register_for_test(spec)
    manager.set_failure_callback(failures.append)
    manager.suspend_capture()
    api.fail_vk = spec.vk

    assert manager.resume_capture() is False
    assert manager._capture_suspended is True
    assert len(failures) == 1
    assert "capture hotkey resume failed" in str(failures[0])
    assert api.registered == {CANCEL_ID: api.registered[CANCEL_ID]}


def test_reregister_during_suspend_keeps_capture_paused_and_f8_available():
    api = FakeHotkeyApi()
    manager = HotkeyManager(api)
    spec = parse_hotkey("alt+backtick")
    manager.register_for_test(spec)
    manager.suspend_capture()

    assert manager.reregister() is True
    assert manager._capture_suspended is True
    assert set(api.registered) == {CANCEL_ID}
    assert manager.resume_capture() is True
    assert api.registered[CAPTURE_IDS[0]][1] == spec.vk


def test_suspend_and_resume_mutations_run_on_message_thread():
    api = FakeHotkeyApi()
    manager = HotkeyManager(api)
    manager.start(parse_hotkey("alt+backtick"), lambda: None, lambda: None)
    message_thread_id = manager._message_thread.ident

    assert manager.suspend_capture() is True
    assert manager.resume_capture() is True
    manager.stop()

    mutations = [call for call in api.calls if call[0] in {"register", "unregister"}]
    assert {call[-1] for call in mutations} == {message_thread_id}


def make_callback_recorder(on_start=None, on_finish=None):
    entry = Entry()
    variable = Variable("alt+backtick")
    status = Variable("")
    recorder = ShortcutRecorder(
        entry,
        variable,
        status,
        on_start=on_start,
        on_finish=on_finish,
    )
    return recorder, entry, variable, status


@pytest.mark.parametrize("finish_result", [True, False])
def test_recorder_suspends_before_recording_and_reports_restore_failure(finish_result):
    calls = []
    recorder, _entry, variable, status = make_callback_recorder(
        on_start=lambda: calls.append("suspend") or True,
        on_finish=lambda: calls.append("resume") or finish_result,
    )

    recorder.start()
    assert calls == ["suspend"]
    assert recorder.is_recording
    recorder.handle_key(SimpleNamespace(keysym="q", state=0))

    assert calls == ["suspend", "resume"]
    assert variable.get() == "q"
    if finish_result:
        assert status.get() == ""
    else:
        assert "could not be restored" in status.get()


def test_recorder_stays_idle_when_capture_cannot_be_suspended():
    recorder, entry, variable, status = make_callback_recorder(on_start=lambda: False)

    recorder.start()

    assert not recorder.is_recording
    assert not entry.focused
    assert variable.get() == "alt+backtick"
    assert "could not be paused" in status.get()


def test_recorder_cancel_resumes_capture_and_preserves_restore_error():
    calls = []
    recorder, _entry, variable, status = make_callback_recorder(
        on_start=lambda: True,
        on_finish=lambda: calls.append("resume") or False,
    )
    recorder.start()

    recorder.handle_key(SimpleNamespace(keysym="Escape", state=0))

    assert calls == ["resume"]
    assert variable.get() == "alt+backtick"
    assert not recorder.is_recording
    assert "could not be restored" in status.get()
