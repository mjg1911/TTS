"""Recorder lifetime integrates with global shortcut registration."""

from tests.windows_tray.test_settings_window_actions import _window
from tests.windows_tray.test_settings_window import drain_apply
from tests.windows_tray.test_settings_apply import make_controller
from piper.windows_tray.controller import SettingsApplyResult


class RecordingOwner:
    def __init__(self):
        self.events = []

    def begin_shortcut_recording(self):
        self.events.append("suspend")
        return True

    def end_shortcut_recording(self):
        self.events.append("resume")
        return True

    def apply(self, *_args):
        return SettingsApplyResult(True)


def test_closing_settings_restores_suspended_shortcut(monkeypatch):
    owner = RecordingOwner()
    window = _window(monkeypatch, owner.apply)
    window.shortcut_recorder.start()
    assert owner.events == ["suspend"]
    window.close()
    assert owner.events == ["suspend", "resume"]


def test_saving_restores_shortcut_before_apply(monkeypatch):
    owner = RecordingOwner()
    window = _window(monkeypatch, owner.apply)
    window.shortcut_recorder.start()
    window._apply()
    drain_apply(window)
    assert owner.events == ["suspend", "resume"]
    assert window.apply_status_var.get() == "Saved."


def test_controller_reports_global_shortcut_restore_failure():
    class Hotkeys:
        def resume_capture(self):
            return False

    status, logs = [], []
    controller = make_controller(hotkeys=Hotkeys())
    controller.configure_runtime(show_status=status.append, log_error=logs.append)
    assert controller.end_shortcut_recording() is False
    assert "could not be restored" in status[0]
    assert logs
