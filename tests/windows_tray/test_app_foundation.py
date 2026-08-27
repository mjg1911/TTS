from pathlib import Path

from piper.windows_tray.commands import CommandKind


def test_tray_menu_callbacks_only_enqueue_commands(monkeypatch, tmp_path: Path) -> None:
    import piper.windows_tray.tray_icon as tray_icon

    class FakeImage:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class FakeImageApi:
        @staticmethod
        def open(_path):
            return FakeImage()

    class FakeMenuItem:
        def __init__(self, text, action):
            self.text = text
            self.action = action

    class FakeMenu:
        def __init__(self, *items):
            self.items = items

    class FakeIcon:
        def __init__(self, _name, _image, _title, menu):
            self.menu = menu

        def run_detached(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(tray_icon, "Image", FakeImageApi)
    monkeypatch.setattr(tray_icon.pystray, "MenuItem", FakeMenuItem)
    monkeypatch.setattr(tray_icon.pystray, "Menu", FakeMenu)
    monkeypatch.setattr(tray_icon.pystray, "Icon", FakeIcon)

    commands = []
    tray = tray_icon.TrayIcon(tmp_path / "icon.png", commands.append)
    for item in tray._icon.menu.items:
        item.action(None, item)

    assert [command.kind for command in commands] == [
        CommandKind.CONFIGURE_VOICE,
        CommandKind.OPEN_LOG,
        CommandKind.EXIT,
    ]


def test_secondary_process_closes_without_loading_or_creating_ui(monkeypatch) -> None:
    import piper.windows_tray.app as app

    calls = []

    class FakeInstance:
        def acquire(self):
            calls.append("acquire")
            return app.InstanceRole.SECONDARY

        def close(self):
            calls.append("close")

    monkeypatch.setattr(app, "SingleInstance", FakeInstance)
    monkeypatch.setattr(
        app,
        "load_settings",
        lambda: calls.append("load_settings"),
    )

    assert app.run_app([]) == 0
    assert calls == ["acquire", "close"]
