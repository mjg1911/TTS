from .commands import Command, CommandKind


def _load_dependencies():
    import pystray
    from PIL import Image

    return pystray, Image


class TrayIcon:
    def __init__(self, icon_path, enqueue, snapshot_provider=None) -> None:
        self._icon_path = icon_path
        self._enqueue = enqueue
        self._snapshot_provider = snapshot_provider or (
            lambda: type("Snapshot", (), {"can_stop": True, "can_replay": True})()
        )
        self._icon = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def _build_icon(self):
        pystray, image_api = _load_dependencies()

        return pystray.Icon(
            "Piper",
            image_api.open(self._icon_path),
            "Piper",
            menu=pystray.Menu(
                pystray.MenuItem(
                    "Voice settings",
                    lambda _icon, _item: self._enqueue(
                        Command(CommandKind.CONFIGURE_VOICE)
                    ),
                ),
                pystray.MenuItem(
                    "Show last text",
                    lambda _icon, _item: self._enqueue(
                        Command(CommandKind.SHOW_LAST_TEXT)
                    ),
                ),
                pystray.MenuItem(
                    "Stop speaking",
                    lambda _icon, _item: self._enqueue(
                        Command(CommandKind.STOP_REQUEST)
                    ),
                    enabled=lambda _item: self._snapshot_provider().can_stop,
                ),
                pystray.MenuItem(
                    "Replay",
                    lambda _icon, _item: self._enqueue(
                        Command(CommandKind.REPLAY_REQUEST)
                    ),
                    enabled=lambda _item: self._snapshot_provider().can_replay,
                ),
                pystray.MenuItem(
                    "Hotkey settings",
                    lambda _icon, _item: self._enqueue(
                        Command(CommandKind.CONFIGURE_HOTKEY)
                    ),
                ),
                pystray.MenuItem(
                    "Open log",
                    lambda _icon, _item: self._enqueue(
                        Command(CommandKind.OPEN_LOG)
                    ),
                ),
                pystray.MenuItem(
                    "Exit",
                    lambda _icon, _item: self._enqueue(Command(CommandKind.EXIT)),
                ),
            ),
        )

    def set_snapshot_provider(self, snapshot_provider) -> None:
        self._snapshot_provider = snapshot_provider

    def start(self) -> None:
        if self._running:
            return

        icon = self._build_icon()
        try:
            icon.run_detached()
        except BaseException:
            self._icon = None
            self._running = False
            raise

        self._icon = icon
        self._running = True

    def ensure_visible(self) -> None:
        if not self._running or self._icon is None:
            self.start()
        else:
            self.update_menu()

    def stop(self) -> None:
        icon = self._icon
        if icon is None:
            self._running = False
            return

        try:
            icon.stop()
        finally:
            self._icon = None
            self._running = False

    def update_menu(self) -> None:
        if self._icon is not None:
            self._icon.update_menu()
