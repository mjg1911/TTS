from dataclasses import dataclass
from dataclasses import replace
from queue import Empty, Queue
from pathlib import Path
from typing import Callable, Optional, Tuple

from .commands import Command, CommandKind
from .settings import TraySettings


VOICE_SETUP_ERRORS = (
    FileNotFoundError,
    OSError,
    ValueError,
    KeyError,
    TypeError,
    RuntimeError,
)


@dataclass
class AppState:
    last_text: Optional[str] = None
    shutting_down: bool = False
    settings: Optional[TraySettings] = None
    voice_path: Optional[Path] = None
    voice: Optional[object] = None


class Controller:
    def __init__(
        self,
        settings: Optional[TraySettings] = None,
        save_settings: Optional[Callable[[TraySettings], None]] = None,
    ) -> None:
        self.state = AppState(settings=settings)
        self._commands = Queue()  # type: Queue[Command]
        self._save_settings = save_settings
        self._choose_voice: Callable[[], Optional[Path]] = lambda: None
        self._load_voice: Callable[[str], Tuple[Path, object]] = (
            lambda _reference: (_ for _ in ()).throw(
                RuntimeError("voice loader is not configured")
            )
        )
        self._show_status: Callable[[str], None] = lambda _message: None
        self._log_error: Callable[[str], None] = lambda _message: None
        self._open_log: Callable[[], None] = lambda: None
        self._stop_tray: Callable[[], None] = lambda: None
        self._close_instance: Callable[[], None] = lambda: None
        self._quit_root: Callable[[], None] = lambda: None

    def configure_runtime(
        self,
        choose_voice: Callable[[], Optional[Path]],
        load_voice: Callable[[str], Tuple[Path, object]],
        show_status: Callable[[str], None],
        log_error: Callable[[str], None],
        open_log: Optional[Callable[[], None]] = None,
        stop_tray: Optional[Callable[[], None]] = None,
        close_instance: Optional[Callable[[], None]] = None,
        quit_root: Optional[Callable[[], None]] = None,
    ) -> None:
        self._choose_voice = choose_voice
        self._load_voice = load_voice
        self._show_status = show_status
        self._log_error = log_error
        if open_log is not None:
            self._open_log = open_log
        if stop_tray is not None:
            self._stop_tray = stop_tray
        if close_instance is not None:
            self._close_instance = close_instance
        if quit_root is not None:
            self._quit_root = quit_root

    def set_voice(self, path: Path, voice: object) -> None:
        self.state.voice_path = path
        self.state.voice = voice

    def install_voice(self, path: Path, voice: object, persist: bool = False) -> bool:
        next_settings = self.state.settings
        if persist:
            if next_settings is None or self._save_settings is None:
                raise RuntimeError("settings persistence is not configured")
            next_settings = replace(next_settings, voice=str(path))
            try:
                self._save_settings(next_settings)
            except (OSError, ValueError) as error:
                self._log_error("Could not save Piper voice settings: %s" % error)
                self._show_status("Piper voice settings could not be saved.")
                return False
        self.state.settings = next_settings
        self.set_voice(path, voice)
        return True

    def enqueue(self, command: Command) -> None:
        self._commands.put(command)

    def drain_once(self) -> Optional[Command]:
        try:
            command = self._commands.get_nowait()
        except Empty:
            return None
        if command.kind is CommandKind.EXIT:
            self.state.shutting_down = True
        return command

    def handle(self, command: Command) -> None:
        if command.kind is CommandKind.ACTIVATE:
            self._show_status("Piper is already running.")
        elif command.kind is CommandKind.OPEN_LOG:
            self._open_log()
        elif command.kind is CommandKind.CONFIGURE_VOICE:
            selected = self._choose_voice()
            if selected is None:
                return
            try:
                candidate_path, candidate_voice = self._load_voice(str(selected))
            except VOICE_SETUP_ERRORS as error:
                self._log_error("Selected Piper voice could not be loaded: %s" % error)
                self._show_status("The selected Piper voice model could not be loaded.")
                return
            self.install_voice(candidate_path, candidate_voice, persist=True)
        elif command.kind is CommandKind.EXIT:
            self._stop_tray()
            self._close_instance()
            self._quit_root()
