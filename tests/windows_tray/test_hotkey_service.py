import queue
import threading

import pytest

from piper.windows_tray.hotkey import MOD_NOREPEAT, VK_F8, parse_hotkey
from piper.windows_tray.hotkey_service import (
    CANCEL_ID,
    CAPTURE_IDS,
    HotkeyManager,
    WM_HOTKEY,
    WM_QUIT,
)


class FakeHotkeyApi:
    def __init__(self) -> None:
        self.registered = {}
        self.fail_vk = None
        self.calls = []
        self.messages = queue.Queue()

    def register(self, hotkey_id: int, modifiers: int, vk: int) -> bool:
        self.calls.append(("register", hotkey_id, modifiers, vk, threading.get_ident()))
        if vk == self.fail_vk:
            return False
        self.registered[hotkey_id] = (modifiers, vk)
        return True

    def unregister(self, hotkey_id: int) -> None:
        self.calls.append(("unregister", hotkey_id, threading.get_ident()))
        self.registered.pop(hotkey_id, None)

    def get_message(self):
        message, wparam = self.messages.get()
        return 1, message, wparam

    def post_command(self, thread_id: int) -> bool:
        self.calls.append(("post_command", thread_id, threading.get_ident()))
        self.messages.put((0x8001, 0))
        return True

    def post_quit(self, thread_id: int) -> bool:
        self.calls.append(("post_quit", thread_id, threading.get_ident()))
        self.messages.put((WM_QUIT, 0))
        return True


def test_failed_rebind_keeps_old_capture_registration() -> None:
    api = FakeHotkeyApi()
    manager = HotkeyManager(api)
    old = parse_hotkey("alt+backtick")
    manager.register_for_test(old)
    api.fail_vk = ord("Q")

    assert manager.rebind(parse_hotkey("ctrl+q")) is False
    assert manager.capture_spec == old
    assert api.registered[CAPTURE_IDS[0]][1] == old.vk


def test_rebind_registers_inactive_id_before_removing_active_id() -> None:
    api = FakeHotkeyApi()
    manager = HotkeyManager(api)
    manager.register_for_test(parse_hotkey("alt+backtick"))

    assert manager.rebind(parse_hotkey("ctrl+q")) is True
    assert manager.capture_spec.vk == ord("Q")
    assert api.registered[CAPTURE_IDS[1]][1] == ord("Q")
    assert [call[0:2] for call in api.calls[-2:]] == [
        ("register", CAPTURE_IDS[1]),
        ("unregister", CAPTURE_IDS[0]),
    ]


def test_register_for_test_registers_capture_and_f8_once() -> None:
    api = FakeHotkeyApi()
    manager = HotkeyManager(api)
    manager.register_for_test(parse_hotkey("alt+backtick"))

    assert set(api.registered) == {CAPTURE_IDS[0], CANCEL_ID}
    assert api.registered[CANCEL_ID] == (MOD_NOREPEAT, VK_F8)


def test_register_for_test_rolls_back_capture_when_f8_conflicts() -> None:
    api = FakeHotkeyApi()
    api.fail_vk = VK_F8
    manager = HotkeyManager(api)

    with pytest.raises(OSError, match="F8 registration failed"):
        manager.register_for_test(parse_hotkey("alt+backtick"))
    assert api.registered == {}
    assert manager.capture_spec is None


def test_message_thread_only_invokes_callbacks_for_hotkey_messages() -> None:
    api = FakeHotkeyApi()
    manager = HotkeyManager(api)
    events = []
    manager.register_for_test(parse_hotkey("alt+backtick"))

    manager.dispatch_message(WM_HOTKEY, CAPTURE_IDS[0], lambda: events.append("capture"), lambda: events.append("cancel"))
    manager.dispatch_message(WM_HOTKEY, CANCEL_ID, lambda: events.append("capture"), lambda: events.append("cancel"))
    manager.dispatch_message(WM_HOTKEY, 999, lambda: events.append("capture"), lambda: events.append("cancel"))
    manager.dispatch_message(WM_QUIT, 0, lambda: events.append("capture"), lambda: events.append("cancel"))

    assert events == ["capture", "cancel"]


def test_stop_unregisters_both_capture_ids_and_posts_quit() -> None:
    api = FakeHotkeyApi()
    manager = HotkeyManager(api)
    manager.register_for_test(parse_hotkey("alt+backtick"))
    manager.stop()

    assert api.registered == {}
    assert [call[0:2] for call in api.calls[-3:]] == [
        ("unregister", CAPTURE_IDS[1]),
        ("unregister", CANCEL_ID),
    ]


def test_production_lifecycle_mutations_run_on_message_thread() -> None:
    api = FakeHotkeyApi()
    manager = HotkeyManager(api)
    caller_thread = threading.get_ident()

    manager.start(parse_hotkey("alt+backtick"), lambda: None, lambda: None)
    manager.rebind(parse_hotkey("ctrl+q"))
    manager.reregister()
    manager.stop()

    mutation_calls = [call for call in api.calls if call[0] in {"register", "unregister"}]
    mutation_threads = {call[-1] for call in mutation_calls}
    assert len(mutation_threads) == 1
    assert caller_thread not in mutation_threads

    rebind_calls = mutation_calls[2:4]
    assert rebind_calls[0][0:2] == ("register", CAPTURE_IDS[1])
    assert rebind_calls[1][0:2] == ("unregister", CAPTURE_IDS[0])


def test_production_reregister_rolls_back_on_f8_conflict() -> None:
    api = FakeHotkeyApi()
    manager = HotkeyManager(api)
    manager.start(parse_hotkey("alt+backtick"), lambda: None, lambda: None)
    api.fail_vk = VK_F8

    assert manager.reregister() is False
    assert api.registered == {}
    manager.stop()
