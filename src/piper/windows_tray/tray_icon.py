from .commands import Command, CommandKind


def _load_dependencies():
    import pystray
    from PIL import Image

    return pystray, Image


class TrayIcon:
    def __init__(self, icon_path, enqueue) -> None:
        pystray, image_api = _load_dependencies()
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

    def start(self) -> None:
        self._icon.run_detached()

    def stop(self) -> None:
        self._icon.stop()
