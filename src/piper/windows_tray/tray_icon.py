import pystray
from PIL import Image

from .commands import Command, CommandKind


class TrayIcon:
    def __init__(self, icon_path, enqueue) -> None:
        self._icon = pystray.Icon(
            "Piper",
            Image.open(icon_path),
            "Piper",
            menu=pystray.Menu(
                pystray.MenuItem(
                    "Voice settings",
                    lambda _icon, _item: enqueue(
                        Command(CommandKind.CONFIGURE_VOICE)
                    ),
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
