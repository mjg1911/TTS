from pathlib import Path
from types import SimpleNamespace

import pytest

from piper.windows_tray.commands import CommandKind
import piper.windows_tray.tray_icon as tray_icon


def install_fake_pystray(monkeypatch, icon):
    class FakeIcon:
        def __init__(self, _name, _image, _title, menu):
            if isinstance(icon, dict):
                icon["menu"] = menu
            else:
                icon.menu = menu

        def run_detached(self):
            pass

        def notify(self, message, title):
            return icon.notify(message, title)

    class FakePystray:
        MenuItem = lambda text, action, enabled=None, checked=None: SimpleNamespace(
            text=text,
            action=action,
            enabled=enabled,
            checked=checked,
        )
        Menu = lambda *items: SimpleNamespace(items=items)
        Icon = FakeIcon

    class FakeImageApi:
        @staticmethod
        def open(_path):
            return object()

    monkeypatch.setattr(
        tray_icon,
        "_load_dependencies",
        lambda: (FakePystray, FakeImageApi),
    )


def test_error_sounds_checkmark_reads_current_snapshot(monkeypatch, tmp_path: Path):
    icon = {}
    install_fake_pystray(monkeypatch, icon)
    snapshot = SimpleNamespace(error_sounds_enabled=False, can_stop=False, can_replay=False)
    tray = tray_icon.TrayIcon(tmp_path / "icon.png", lambda _command: None, lambda: snapshot)

    tray.start()
    item = next(item for item in icon["menu"].items if item.text == "Error sounds")

    assert item.checked(item) is False
    snapshot.error_sounds_enabled = True
    assert item.checked(item) is True


def test_error_sounds_callback_only_enqueues_toggle_command(monkeypatch, tmp_path: Path):
    icon = {}
    install_fake_pystray(monkeypatch, icon)
    commands = []
    snapshot = SimpleNamespace(error_sounds_enabled=False, can_stop=False, can_replay=False)
    tray = tray_icon.TrayIcon(tmp_path / "icon.png", commands.append, lambda: snapshot)

    tray.start()
    item = next(item for item in icon["menu"].items if item.text == "Error sounds")
    item.action(None, item)

    assert [command.kind for command in commands] == [CommandKind.TOGGLE_ERROR_SOUNDS]


def test_show_notification_delegates_to_native_icon(monkeypatch, tmp_path: Path):
    notifications = []
    icon = SimpleNamespace(notify=lambda message, title: notifications.append((message, title)))
    install_fake_pystray(monkeypatch, icon)
    tray = tray_icon.TrayIcon(tmp_path / "icon.png", lambda _command: None)

    tray.start()
    tray.show_notification("No text selected")

    assert notifications == [("No text selected", "Piper")]


def test_show_notification_propagates_native_failure(monkeypatch, tmp_path: Path):
    error = OSError("notification failed")
    icon = SimpleNamespace(notify=lambda _message, _title: (_ for _ in ()).throw(error))
    install_fake_pystray(monkeypatch, icon)
    tray = tray_icon.TrayIcon(tmp_path / "icon.png", lambda _command: None)

    tray.start()

    with pytest.raises(OSError, match="notification failed"):
        tray.show_notification("No text selected")
