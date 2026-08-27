from dataclasses import dataclass
from dataclasses import replace
from queue import Empty, Queue
from pathlib import Path
import threading
from typing import Callable, Optional, Tuple

from .capture import CaptureResult, CaptureStatus
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
    capture_generation: int = 0
    capture_in_progress: bool = False
    shutting_down: bool = False
    settings: Optional[TraySettings] = None
    voice_path: Optional[Path] = None
    voice: Optional[object] = None


@dataclass(frozen=True)
class CaptureCompletion:
    generation: int
    result: CaptureResult


def _start_daemon_job(job: Callable[[], None]) -> None:
    threading.Thread(target=job, name="piper-capture", daemon=True).start()


class Controller:
    def __init__(
        self,
        settings: Optional[TraySettings] = None,
        save_settings: Optional[Callable[[TraySettings], None]] = None,
        capture: Optional[Callable[[], CaptureResult]] = None,
        capture_submit: Optional[Callable[[Callable[[], None]], None]] = None,
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
        self._capture = capture or (
            lambda: CaptureResult(CaptureStatus.ACCESS_ERROR, detail="capture is not configured")
        )
        self._capture_submit = capture_submit or _start_daemon_job
        self._log_info: Callable[[str], None] = lambda _message: None
        self._show_last_text: Callable[[Optional[str]], None] = lambda _text: None

    def configure_runtime(
        self,
        choose_voice: Optional[Callable[[], Optional[Path]]] = None,
        load_voice: Optional[Callable[[str], Tuple[Path, object]]] = None,
        show_status: Optional[Callable[[str], None]] = None,
        log_error: Optional[Callable[[str], None]] = None,
        open_log: Optional[Callable[[], None]] = None,
        stop_tray: Optional[Callable[[], None]] = None,
        close_instance: Optional[Callable[[], None]] = None,
        quit_root: Optional[Callable[[], None]] = None,
        capture: Optional[Callable[[], CaptureResult]] = None,
        capture_submit: Optional[Callable[[Callable[[], None]], None]] = None,
        log_info: Optional[Callable[[str], None]] = None,
        show_last_text: Optional[Callable[[Optional[str]], None]] = None,
    ) -> None:
        if choose_voice is not None:
            self._choose_voice = choose_voice
        if load_voice is not None:
            self._load_voice = load_voice
        if show_status is not None:
            self._show_status = show_status
        if log_error is not None:
            self._log_error = log_error
        if open_log is not None:
            self._open_log = open_log
        if stop_tray is not None:
            self._stop_tray = stop_tray
        if close_instance is not None:
            self._close_instance = close_instance
        if quit_root is not None:
            self._quit_root = quit_root
        if capture is not None:
            self._capture = capture
        if capture_submit is not None:
            self._capture_submit = capture_submit
        if log_info is not None:
            self._log_info = log_info
        if show_last_text is not None:
            self._show_last_text = show_last_text

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
        elif command.kind is CommandKind.CAPTURE_REQUEST:
            self._request_capture()
        elif command.kind in (CommandKind.CAPTURE_SUCCEEDED, CommandKind.CAPTURE_FAILED):
            self._complete_capture(command)
        elif command.kind is CommandKind.SHOW_LAST_TEXT:
            self._show_last_text(self.state.last_text)
        elif command.kind is CommandKind.CANCEL_REQUEST:
            return
        elif command.kind is CommandKind.EXIT:
            self._stop_tray()
            self._close_instance()
            self._quit_root()

    def _request_capture(self) -> None:
        if self.state.capture_in_progress:
            return
        self.state.capture_generation += 1
        generation = self.state.capture_generation
        self.state.capture_in_progress = True

        def worker() -> None:
            try:
                result = self._capture()
            except Exception as error:
                result = CaptureResult(CaptureStatus.ACCESS_ERROR, detail=str(error))
            self._log_info(
                "capture outcome=%s length=%d"
                % (result.status.name, len(result.text) if result.text is not None else 0)
            )
            kind = (
                CommandKind.CAPTURE_SUCCEEDED
                if result.status is CaptureStatus.SUCCESS
                else CommandKind.CAPTURE_FAILED
            )
            self.enqueue(Command(kind, CaptureCompletion(generation, result)))

        self._capture_submit(worker)

    def _complete_capture(self, command: Command) -> None:
        completion = command.value
        if isinstance(completion, CaptureCompletion):
            generation, result = completion.generation, completion.result
        elif isinstance(completion, CaptureResult):
            generation, result = self.state.capture_generation, completion
        elif isinstance(completion, str):
            generation = self.state.capture_generation
            result = CaptureResult(CaptureStatus.SUCCESS, completion)
        else:
            return
        if generation != self.state.capture_generation:
            return
        self.state.capture_in_progress = False
        if (
            command.kind is CommandKind.CAPTURE_SUCCEEDED
            and result.status is CaptureStatus.SUCCESS
            and result.text is not None
        ):
            self.state.last_text = result.text
