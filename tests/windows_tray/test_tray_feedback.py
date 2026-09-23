from pathlib import Path
from types import SimpleNamespace

import pytest

from piper.windows_tray.commands import CommandKind
import piper.windows_tray.tray_icon as tray_icon


def install_fake_pystray(monkeypatch, icon):
    class FakeIcon:
        def __init__(self, _name, _image, title, menu):
            self.external = icon
            if isinstance(icon, dict):
                icon["menu"] = menu
                icon["updates"] = 0
            else:
                icon.menu = menu
                icon.updates = 0
            self.title = title

        @property
        def title(self):
            return self._title

        @title.setter
        def title(self, value):
            self._title = value
            if isinstance(self.external, dict):
                self.external["title"] = value
            else:
                self.external.title = value

        def run_detached(self):
            pass

        def stop(self):
            pass

        def update_menu(self):
            icon["updates"] += 1 if isinstance(icon, dict) else 0

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
    icon = SimpleNamespace(notify=lambda *args, **kwargs: notifications.append((args, kwargs)))
    install_fake_pystray(monkeypatch, icon)
    tray = tray_icon.TrayIcon(tmp_path / "icon.png", lambda _command: None)

    tray.start()
    tray.show_notification("Test notification")

    assert notifications == [(('Test notification', 'Piper'), {})]


def test_fallback_snapshot_disables_error_sounds():
    tray = tray_icon.TrayIcon(Path("icon.png"), lambda _command: None)

    assert tray._snapshot_provider().error_sounds_enabled is False


@pytest.mark.parametrize("action", ["before_start", "after_stop"])
def test_show_notification_requires_running_tray(monkeypatch, tmp_path: Path, action: str):
    icon = SimpleNamespace(notify=lambda *_args, **_kwargs: None)
    install_fake_pystray(monkeypatch, icon)
    tray = tray_icon.TrayIcon(tmp_path / "icon.png", lambda _command: None)

    if action == "after_stop":
        tray.start()
        tray.stop()

    with pytest.raises(RuntimeError, match="^tray icon is not running$"):
        tray.show_notification("Test notification")


def test_show_notification_propagates_native_failure(monkeypatch, tmp_path: Path):
    error = OSError("notification failed")
    icon = SimpleNamespace(notify=lambda _message, _title: (_ for _ in ()).throw(error))
    install_fake_pystray(monkeypatch, icon)
    tray = tray_icon.TrayIcon(tmp_path / "icon.png", lambda _command: None)

    tray.start()

    with pytest.raises(OSError, match="notification failed"):
        tray.show_notification("Test notification")


def test_default_title_reports_piper_ready(monkeypatch, tmp_path: Path):
    icon = {}
    install_fake_pystray(monkeypatch, icon)
    tray = tray_icon.TrayIcon(tmp_path / "icon.png", lambda _command: None)

    tray.start()

    assert icon["title"] == "Piper is ready"


@pytest.mark.parametrize("when", ["before_start", "after_start"])
def test_set_status_updates_title_and_refreshes_menu(monkeypatch, tmp_path: Path, when):
    icon = {}
    install_fake_pystray(monkeypatch, icon)
    tray = tray_icon.TrayIcon(tmp_path / "icon.png", lambda _command: None)

    if when == "after_start":
        tray.start()
    tray.set_status("Kokoro is loading")

    if when == "before_start":
        tray.start()
    assert icon["title"] == "Kokoro is loading"
    assert icon["updates"] == (1 if when == "after_start" else 0)


def test_set_status_after_start_refreshes_menu_and_uses_unavailable_title(monkeypatch, tmp_path: Path):
    icon = {}
    install_fake_pystray(monkeypatch, icon)
    tray = tray_icon.TrayIcon(tmp_path / "icon.png", lambda _command: None)
    tray.start()

    tray.set_status("Kokoro unavailable; Piper is ready")

    assert icon["title"] == "Kokoro unavailable; Piper is ready"
    assert icon["updates"] == 1
