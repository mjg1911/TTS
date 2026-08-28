import threading

from piper.windows_tray.power_events import (
    PBT_APMRESUMEAUTOMATIC,
    PBT_APMRESUMESUSPEND,
    PowerBroadcastListener,
    is_resume_event,
)
from piper.windows_tray.power_events import _Win32PowerApi


class FakePowerApi:
    def __init__(self) -> None:
        self.created = threading.Event()
        self.release = threading.Event()
        self.callback = None
        self.posted_close = []
        self.message_loop_calls = 0

    def create_hidden_window(self, on_resume):
        self.callback = on_resume
        self.created.set()
        return 77

    def message_loop(self) -> None:
        self.message_loop_calls += 1
        self.release.wait(timeout=1.0)

    def post_close(self, hwnd: int) -> None:
        self.posted_close.append(hwnd)
        self.release.set()


def test_only_automatic_resume_is_the_canonical_recovery_event() -> None:
    assert is_resume_event(PBT_APMRESUMEAUTOMATIC)
    assert not is_resume_event(PBT_APMRESUMESUSPEND)
    assert not is_resume_event(0x0004)


def test_listener_runs_callback_from_power_window() -> None:
    api = FakePowerApi()
    listener = PowerBroadcastListener(api=api)
    resumed = []

    listener.start(lambda: resumed.append("resume"))
    assert api.created.wait(timeout=1.0)

    api.callback()
    listener.stop()

    assert resumed == ["resume"]
    assert api.posted_close == [77]


def test_listener_stop_is_idempotent() -> None:
    api = FakePowerApi()
    listener = PowerBroadcastListener(api=api)

    listener.start(lambda: None)
    listener.stop()
    listener.stop()

    assert api.posted_close == [77]
    assert api.message_loop_calls == 1


class FakeUser32:
    def __init__(self) -> None:
        self.destroyed = []
        self.quit_codes = []

    def DestroyWindow(self, hwnd: int) -> None:
        self.destroyed.append(hwnd)

    def PostQuitMessage(self, code: int) -> None:
        self.quit_codes.append(code)

    def DefWindowProcW(self, hwnd, message, w_param, l_param):
        return 99


def test_wm_close_destroys_hidden_window() -> None:
    api = object.__new__(_Win32PowerApi)
    api._WNDPROC = lambda callback: callback
    api._user32 = FakeUser32()

    wndproc = api._make_wndproc(lambda: None)

    assert wndproc(77, 0x0010, 0, 0) == 0
    assert api._user32.destroyed == [77]


def test_wm_destroy_posts_quit_message() -> None:
    api = object.__new__(_Win32PowerApi)
    api._WNDPROC = lambda callback: callback
    api._user32 = FakeUser32()

    wndproc = api._make_wndproc(lambda: None)

    assert wndproc(77, 0x0002, 0, 0) == 0
    assert api._user32.quit_codes == [0]
