from pathlib import Path

from piper.windows_tray.capture import CaptureResult, CaptureStatus
from piper.windows_tray.commands import Command, CommandKind
from piper.windows_tray.controller import CaptureCompletion, Controller
from piper.windows_tray.settings import TraySettings


class FakeHotkeys:
    def __init__(self, result=True):
        self.result = result
        self.candidates = []

    def rebind(self, candidate):
        self.candidates.append(candidate)
        return self.result


def test_settings_change_only_after_native_rebind_succeeds():
    settings = TraySettings(hotkey="alt+backtick")
    saved = []
    notifications = []
    hotkeys = FakeHotkeys(result=False)
    controller = Controller(settings=settings, save_settings=saved.append)
    controller.configure_runtime(
        hotkeys=hotkeys,
        show_status=notifications.append,
        choose_hotkey=lambda: "ctrl+q",
    )

    controller.handle(Command(CommandKind.CONFIGURE_HOTKEY))

    assert controller.state.settings == settings
    assert saved == []
    assert notifications[-1] == "That hotkey is already in use. Choose another combination."


def test_successful_rebind_persists_canonical_hotkey_after_registration():
    settings = TraySettings(hotkey="alt+backtick")
    saved = []
    hotkeys = FakeHotkeys(result=True)
    controller = Controller(settings=settings, save_settings=saved.append)
    controller.configure_runtime(hotkeys=hotkeys, choose_hotkey=lambda: "Ctrl + Q")

    controller.handle(Command(CommandKind.CONFIGURE_HOTKEY))

    assert controller.state.settings.hotkey == "ctrl+q"
    assert saved == [controller.state.settings]
    assert hotkeys.candidates[0].canonical == "ctrl+q"


def test_generationless_capture_success_is_ignored():
    controller = Controller()
    controller.handle(Command(CommandKind.CAPTURE_REQUEST))

    controller.handle(
        Command(
            CommandKind.CAPTURE_SUCCEEDED,
            CaptureResult(CaptureStatus.SUCCESS, "untrusted"),
        )
    )

    assert controller.state.last_text is None
    assert controller.state.capture_in_progress is True

def test_stale_generation_completion_does_not_clear_current_capture():
    controller = Controller(capture_submit=lambda _job: None)
    controller.handle(Command(CommandKind.CAPTURE_REQUEST))
    controller.handle(
        Command(
            CommandKind.CAPTURE_SUCCEEDED,
            CaptureCompletion(0, CaptureResult(CaptureStatus.SUCCESS, "stale")),
        )
    )

    assert controller.state.last_text is None
    assert controller.state.capture_in_progress is True
