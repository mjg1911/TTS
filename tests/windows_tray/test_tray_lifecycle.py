from pathlib import Path
from types import SimpleNamespace

import piper.windows_tray.tray_icon as tray_icon


def install_fake_pystray(monkeypatch, calls):
    class FakeIcon:
        def __init__(self, *_args, **_kwargs):
            calls.append("build")

        def run_detached(self):
            calls.append("start")

        def stop(self):
            calls.append("stop")

        def update_menu(self):
            calls.append("update")

    class FakeImageApi:
        @staticmethod
        def open(_path):
            return object()

    class FakePystray:
        Icon = FakeIcon
        Menu = lambda *items: SimpleNamespace(items=items)
        MenuItem = lambda text, action, enabled=None: SimpleNamespace(
            text=text,
            action=action,
            enabled=enabled,
        )

    monkeypatch.setattr(
        tray_icon,
        "_load_dependencies",
        lambda: (FakePystray, FakeImageApi),
    )


def test_start_is_idempotent(monkeypatch, tmp_path: Path) -> None:
    calls = []
    install_fake_pystray(monkeypatch, calls)

    tray = tray_icon.TrayIcon(tmp_path / "icon.png", lambda _command: None)
    tray.start()
    tray.start()

    assert tray.running is True
    assert calls == ["build", "start"]


def test_stop_then_ensure_visible_builds_a_fresh_icon(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls = []
    install_fake_pystray(monkeypatch, calls)

    tray = tray_icon.TrayIcon(tmp_path / "icon.png", lambda _command: None)

    tray.start()
    tray.stop()

    assert tray.running is False

    tray.ensure_visible()

    assert tray.running is True
    assert calls == [
        "build",
        "start",
        "stop",
        "build",
        "start",
    ]


def test_stop_is_idempotent(monkeypatch, tmp_path: Path) -> None:
    calls = []
    install_fake_pystray(monkeypatch, calls)

    tray = tray_icon.TrayIcon(tmp_path / "icon.png", lambda _command: None)

    tray.start()
    tray.stop()
    tray.stop()

    assert calls.count("stop") == 1
