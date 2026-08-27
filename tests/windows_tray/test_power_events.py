import threading

from piper.windows_tray.power_events import (
    PBT_APMRESUMEAUTOMATIC,
    PBT_APMRESUMESUSPEND,
    PowerBroadcastListener,
    is_resume_event,
)


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
