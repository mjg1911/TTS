from piper.windows_tray.commands import Command, CommandKind
from piper.windows_tray.controller import Controller, PlaybackState
from piper.windows_tray.lifecycle import TeardownCoordinator


def make_teardown(*, on_failure, on_complete, calls):
    return TeardownCoordinator(
        stop_hotkeys=lambda: calls.append("hotkeys"),
        stop_power=lambda: calls.append("power"),
        stop_speech=lambda: calls.append("speech"),
        stop_tray=lambda: calls.append("tray"),
        close_instance=lambda: calls.append("instance"),
        quit_root=lambda: calls.append("quit"),
        on_failure=on_failure,
        on_complete=on_complete,
    )


def test_teardown_runs_resources_in_safe_order() -> None:
    calls = []
    failures = []

    teardown = TeardownCoordinator(
        stop_hotkeys=lambda: calls.append("hotkeys.stop"),
        stop_power=lambda: calls.append("power.stop"),
        stop_speech=lambda: calls.append("speech.shutdown"),
        stop_tray=lambda: calls.append("tray.stop"),
        close_instance=lambda: calls.append("instance.close"),
        quit_root=lambda: calls.append("tk.quit"),
        on_failure=lambda stage, error: failures.append((stage, type(error).__name__)),
        on_complete=lambda: calls.append("complete"),
    )

    teardown.run()

    assert calls == [
        "hotkeys.stop",
        "power.stop",
        "speech.shutdown",
        "tray.stop",
        "instance.close",
        "tk.quit",
        "complete",
    ]
    assert failures == []


def test_teardown_is_idempotent() -> None:
    calls = []

    teardown = TeardownCoordinator(
        stop_hotkeys=lambda: calls.append("hotkeys"),
        stop_power=lambda: calls.append("power"),
        stop_speech=lambda: calls.append("speech"),
        stop_tray=lambda: calls.append("tray"),
        close_instance=lambda: calls.append("instance"),
        quit_root=lambda: calls.append("quit"),
        on_failure=lambda _stage, _error: None,
        on_complete=lambda: None,
    )

    teardown.run()
    teardown.run()

    assert calls == ["hotkeys", "power", "speech", "tray", "instance", "quit"]


def test_cleanup_failure_does_not_skip_later_resources() -> None:
    calls = []
    failures = []

    def fail_power():
        calls.append("power")
        raise OSError("stop failed")

    teardown = TeardownCoordinator(
        stop_hotkeys=lambda: calls.append("hotkeys"),
        stop_power=fail_power,
        stop_speech=lambda: calls.append("speech"),
        stop_tray=lambda: calls.append("tray"),
        close_instance=lambda: calls.append("instance"),
        quit_root=lambda: calls.append("quit"),
        on_failure=lambda stage, error: failures.append((stage, type(error).__name__)),
        on_complete=lambda: calls.append("complete"),
    )

    teardown.run()

    assert calls == ["hotkeys", "power", "speech", "tray", "instance", "quit", "complete"]
    assert failures == [("power", "OSError")]


def test_failure_callback_cannot_interrupt_cleanup_or_completion() -> None:
    calls = []

    def fail_power():
        calls.append("power")
        raise OSError("stop failed")

    teardown = TeardownCoordinator(
        stop_hotkeys=lambda: calls.append("hotkeys"),
        stop_power=fail_power,
        stop_speech=lambda: calls.append("speech"),
        stop_tray=lambda: calls.append("tray"),
        close_instance=lambda: calls.append("instance"),
        quit_root=lambda: calls.append("quit"),
        on_failure=lambda _stage, _error: (_ for _ in ()).throw(RuntimeError("report failed")),
        on_complete=lambda: calls.append("complete"),
    )

    teardown.run()

    assert calls == ["hotkeys", "power", "speech", "tray", "instance", "quit", "complete"]


def test_completion_callback_is_called_once_and_cannot_break_repeated_run() -> None:
    calls = []
    teardown = make_teardown(
        calls=calls,
        on_failure=lambda _stage, _error: None,
        on_complete=lambda: (_ for _ in ()).throw(RuntimeError("complete failed")),
    )

    teardown.run()
    teardown.run()

    assert calls == ["hotkeys", "power", "speech", "tray", "instance", "quit"]


def test_concurrent_runs_execute_cleanup_once() -> None:
    import threading

    calls = []
    entered = threading.Event()
    release = threading.Event()

    def stop_hotkeys():
        calls.append("hotkeys")
        entered.set()
        release.wait(timeout=1.0)

    teardown = TeardownCoordinator(
        stop_hotkeys=stop_hotkeys,
        stop_power=lambda: calls.append("power"),
        stop_speech=lambda: calls.append("speech"),
        stop_tray=lambda: calls.append("tray"),
        close_instance=lambda: calls.append("instance"),
        quit_root=lambda: calls.append("quit"),
        on_failure=lambda _stage, _error: None,
        on_complete=lambda: calls.append("complete"),
    )

    first = threading.Thread(target=teardown.run)
    second = threading.Thread(target=teardown.run)
    first.start()
    assert entered.wait(timeout=1.0)
    second.start()
    second.join(timeout=1.0)
    release.set()
    first.join(timeout=1.0)

    assert not first.is_alive()
    assert not second.is_alive()
    assert calls == ["hotkeys", "power", "speech", "tray", "instance", "quit", "complete"]


class FakeSpeech:
    def __init__(self) -> None:
        self.cancelled = []
        self.auxiliary_cancel_calls = 0

    def cancel_active(self, generation: int) -> None:
        self.cancelled.append(generation)

    def cancel_auxiliary(self) -> None:
        self.auxiliary_cancel_calls += 1


def test_shutdown_discards_auxiliary_before_teardown() -> None:
    calls = []
    speech = FakeSpeech()
    controller = Controller(speech_worker=speech)
    controller.configure_runtime(
        request_teardown=lambda: calls.append("teardown")
    )
    controller.state.auxiliary_active = True

    controller.handle(Command(CommandKind.EXIT))

    assert speech.auxiliary_cancel_calls == 1
    assert controller.state.auxiliary_active is False
    assert (
        controller.state.playback
        is PlaybackState.SHUTTING_DOWN
    )
    assert calls == ["teardown"]


def test_controller_exit_cancels_before_requesting_teardown() -> None:
    calls = []
    speech = FakeSpeech()
    controller = Controller(speech_worker=speech)
    controller.configure_runtime(request_teardown=lambda: calls.append("teardown"))
    controller.state.playback = PlaybackState.SPEAKING
    controller.state.speech_generation = 5

    controller.handle(Command(CommandKind.EXIT))

    assert speech.cancelled == [5]
    assert controller.state.speech_generation == 6
    assert controller.state.playback is PlaybackState.SHUTTING_DOWN
    assert controller.state.shutting_down is True
    assert calls == ["teardown"]


def test_second_exit_does_not_request_teardown_twice() -> None:
    calls = []
    controller = Controller()
    controller.configure_runtime(request_teardown=lambda: calls.append("teardown"))

    controller.handle(Command(CommandKind.EXIT))
    controller.handle(Command(CommandKind.EXIT))

    assert calls == ["teardown"]
