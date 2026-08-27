from .commands import Command, CommandKind


def _load_dependencies():
    import pystray
    from PIL import Image

    return pystray, Image


class TrayIcon:
    def __init__(self, icon_path, enqueue, snapshot_provider=None) -> None:
        pystray, image_api = _load_dependencies()
        self._snapshot_provider = snapshot_provider or (
            lambda: type("Snapshot", (), {"can_stop": True, "can_replay": True})()
        )
        self._icon = pystray.Icon(
            "Piper",
            image_api.open(icon_path),
            "Piper",
            menu=pystray.Menu(
                pystray.MenuItem(
                    "Voice settings",
                    lambda _icon, _item: enqueue(
                        Command(CommandKind.CONFIGURE_VOICE)
                    ),
                ),
                pystray.MenuItem(
                    "Show last text",
                    lambda _icon, _item: enqueue(Command(CommandKind.SHOW_LAST_TEXT)),
                ),
                pystray.MenuItem(
                    "Stop speaking",
                    lambda _icon, _item: enqueue(Command(CommandKind.STOP_REQUEST)),
                    enabled=lambda _item: self._snapshot_provider().can_stop,
                ),
                pystray.MenuItem(
                    "Replay",
                    lambda _icon, _item: enqueue(Command(CommandKind.REPLAY_REQUEST)),
                    enabled=lambda _item: self._snapshot_provider().can_replay,
                ),
                pystray.MenuItem(
                    "Hotkey settings",
                    lambda _icon, _item: enqueue(Command(CommandKind.CONFIGURE_HOTKEY)),
                ),
                pystray.MenuItem(
                    "Open log",
                    lambda _icon, _item: enqueue(Command(CommandKind.OPEN_LOG)),
                ),
                pystray.MenuItem(
                    "Exit",
                    lambda _icon, _item: enqueue(Command(CommandKind.EXIT)),
                ),
            ),
        )

    def set_snapshot_provider(self, snapshot_provider) -> None:
        self._snapshot_provider = snapshot_provider

    def start(self) -> None:
        self._icon.run_detached()

    def stop(self) -> None:
        self._icon.stop()

    def update_menu(self) -> None:
        self._icon.update_menu()
