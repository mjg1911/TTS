from dataclasses import dataclass
from dataclasses import replace
from enum import Enum, auto
import logging
from queue import Empty, Queue
from pathlib import Path
import threading
from typing import Callable, Optional, Tuple

from .capture import CaptureResult, CaptureStatus
from .commands import Command, CommandKind
from .hotkey import parse_hotkey
from .logging_setup import log_capture_result, log_exception_safe
from .errors import UserError, user_message
from .settings import TraySettings
from .speech import SpeechEvent, SpeechEventKind, SpeechRequest
from .voice_manager import VoiceManager, VoiceSwitchEvent


_LOGGER = logging.getLogger(__name__)


VOICE_SETUP_ERRORS = (
    FileNotFoundError,
    OSError,
    ValueError,
    KeyError,
    TypeError,
    RuntimeError,
)


class PlaybackState(Enum):
    IDLE = auto()
    SPEAKING = auto()
    STOPPED = auto()
    SHUTTING_DOWN = auto()


@dataclass
class AppState:
    last_text: Optional[str] = None
    capture_generation: int = 0
    capture_in_progress: bool = False
    speech_generation: int = 0
    voice_generation: int = 0
    playback: PlaybackState = PlaybackState.IDLE
    shutting_down: bool = False
    settings: Optional[TraySettings] = None
    voice_path: Optional[Path] = None
    voice: Optional[object] = None


@dataclass(frozen=True)
class CaptureCompletion:
    generation: int
    result: CaptureResult


@dataclass(frozen=True)
class TraySnapshot:
    can_stop: bool
    can_replay: bool
    has_last_text: bool
    error_sounds_enabled: bool


def _start_daemon_job(job: Callable[[], None]) -> None:
    threading.Thread(target=job, name="piper-capture", daemon=True).start()


class Controller:
    def __init__(
        self,
        settings: Optional[TraySettings] = None,
        save_settings: Optional[Callable[[TraySettings], None]] = None,
        capture: Optional[Callable[[], CaptureResult]] = None,
        capture_submit: Optional[Callable[[Callable[[], None]], None]] = None,
        hotkeys: Optional[object] = None,
        speech_worker: Optional[object] = None,
        voice_manager: Optional[VoiceManager] = None,
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
        self._show_notification: Callable[[str], None] = lambda _message: None
        self._log_error: Callable[[str], None] = lambda _message: None
        self._open_log: Callable[[], None] = lambda: None
        self._ensure_tray_visible: Callable[[], None] = lambda: None
        self._request_teardown: Callable[[], None] = lambda: None
        self._capture = capture or (
            lambda: CaptureResult(CaptureStatus.ACCESS_ERROR, detail="capture is not configured")
        )
        self._capture_submit = capture_submit or _start_daemon_job
        self._capture_pending = False
        self._capture_invalidated_on_resume = False
        self._log_info: Callable[[str], None] = lambda _message: None
        self._show_last_text: Callable[[Optional[str]], None] = lambda _text: None
        self._hotkeys = hotkeys
        self._choose_hotkey: Callable[[], Optional[str]] = lambda: None
        self._speech_worker = speech_worker
        self._capture_replaced_speech = False
        self._voice_manager = voice_manager
        self._state_lock = threading.RLock()

    def configure_runtime(
        self,
        choose_voice: Optional[Callable[[], Optional[Path]]] = None,
        load_voice: Optional[Callable[[str], Tuple[Path, object]]] = None,
        show_status: Optional[Callable[[str], None]] = None,
        show_notification: Optional[Callable[[str], None]] = None,
        log_error: Optional[Callable[[str], None]] = None,
        open_log: Optional[Callable[[], None]] = None,
        ensure_tray_visible: Optional[Callable[[], None]] = None,
        request_teardown: Optional[Callable[[], None]] = None,
        capture: Optional[Callable[[], CaptureResult]] = None,
        capture_submit: Optional[Callable[[Callable[[], None]], None]] = None,
        log_info: Optional[Callable[[str], None]] = None,
        show_last_text: Optional[Callable[[Optional[str]], None]] = None,
        hotkeys: Optional[object] = None,
        choose_hotkey: Optional[Callable[[], Optional[str]]] = None,
        speech_worker: Optional[object] = None,
        voice_manager: Optional[VoiceManager] = None,
    ) -> None:
        if choose_voice is not None:
            self._choose_voice = choose_voice
        if load_voice is not None:
            self._load_voice = load_voice
        if show_status is not None:
            self._show_status = show_status
        if show_notification is not None:
            self._show_notification = show_notification
        if log_error is not None:
            self._log_error = log_error
        if open_log is not None:
            self._open_log = open_log
        if ensure_tray_visible is not None:
            self._ensure_tray_visible = ensure_tray_visible
        if request_teardown is not None:
            self._request_teardown = request_teardown
        if capture is not None:
            self._capture = capture
        if capture_submit is not None:
            self._capture_submit = capture_submit
        if log_info is not None:
            self._log_info = log_info
        if show_last_text is not None:
            self._show_last_text = show_last_text
        if hotkeys is not None:
            self._hotkeys = hotkeys
        if choose_hotkey is not None:
            self._choose_hotkey = choose_hotkey
        if speech_worker is not None:
            self._speech_worker = speech_worker
        if voice_manager is not None:
            self._voice_manager = voice_manager
        elif self._voice_manager is None and self.state.voice is not None and load_voice is not None:
            self._voice_manager = VoiceManager(self.state.voice, load_voice)

    def set_voice(self, path: Path, voice: object) -> None:
        with self._state_lock:
            self.state.voice_path = path
            self.state.voice = voice
            if self._voice_manager is not None:
                self._voice_manager.replace(voice)

    def install_voice(self, path: Path, voice: object, persist: bool = False) -> bool:
        with self._state_lock:
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

    def tray_snapshot(self) -> TraySnapshot:
        with self._state_lock:
            return TraySnapshot(
                can_stop=self.state.playback is PlaybackState.SPEAKING,
                can_replay=(
                    self.state.last_text is not None
                    and not self.state.shutting_down
                    and not self.state.capture_in_progress
                ),
                has_last_text=self.state.last_text is not None,
                error_sounds_enabled=(
                    self.state.settings.error_sounds
                    if self.state.settings is not None
                    else False
                ),
            )

    def enqueue_worker_event(self, event: SpeechEvent) -> None:
        """Queue worker output; worker callbacks must not touch controller state."""
        self.enqueue(Command(CommandKind.WORKER_EVENT, event))

    def drain_once(self) -> Optional[Command]:
        try:
            command = self._commands.get_nowait()
        except Empty:
            return None
        return command

    def handle(self, command: Command) -> None:
        with self._state_lock:
            self._handle(command)

    def _handle(self, command: Command) -> None:
        if command.kind is CommandKind.ACTIVATE:
            self._show_status("Piper is already running.")
        elif command.kind is CommandKind.TOGGLE_ERROR_SOUNDS:
            self._toggle_error_sounds()
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
                self._show_status(user_message(UserError.VOICE_LOAD_REPLACEMENT))
                return
            self._stop_speech()
            self.install_voice(candidate_path, candidate_voice, persist=True)
        elif command.kind is CommandKind.CAPTURE_REQUEST:
            self._request_capture()
        elif command.kind in (CommandKind.CAPTURE_SUCCEEDED, CommandKind.CAPTURE_FAILED):
            self._complete_capture(command)
        elif command.kind is CommandKind.SHOW_LAST_TEXT:
            self._show_last_text(self.state.last_text)
        elif command.kind is CommandKind.CONFIGURE_HOTKEY:
            requested = command.value
            if requested is None:
                requested = self._choose_hotkey()
            if isinstance(requested, str):
                self.request_hotkey_change(requested)
        elif command.kind is CommandKind.CANCEL_REQUEST:
            self._stop_speech()
        elif command.kind is CommandKind.STOP_REQUEST:
            self._stop_speech()
        elif command.kind is CommandKind.REPLAY_REQUEST:
            self._replay()
        elif command.kind is CommandKind.WORKER_EVENT:
            self._handle_worker_event(command.value)
        elif command.kind in (
            CommandKind.VOICE_SWITCH_SUCCEEDED,
            CommandKind.VOICE_SWITCH_FAILED,
        ):
            self._handle_voice_switch(command.value)
        elif command.kind is CommandKind.HOTKEY_FAILED:
            detail = str(command.value) if command.value else "unknown error"
            self._log_error("Piper hotkey message loop stopped: %s" % detail)
            self._show_status(
                "Piper hotkeys stopped unexpectedly; hotkeys are unavailable."
            )
        elif command.kind is CommandKind.SYSTEM_RESUME:
            self._recover_from_resume()
        elif command.kind is CommandKind.EXIT:
            if self.state.shutting_down:
                return
            self._begin_shutdown()
            self._request_teardown()

    def _toggle_error_sounds(self) -> bool:
        current = self.state.settings
        if current is None or self._save_settings is None:
            return False
        next_settings = replace(
            current,
            error_sounds=not current.error_sounds,
        )
        try:
            self._save_settings(next_settings)
        except (OSError, ValueError) as error:
            self._log_error("Could not save Piper error sound settings: %s" % error)
            self._show_status("Piper error sound settings could not be saved.")
            return False
        self.state.settings = next_settings
        return True

    def _recover_from_resume(self) -> None:
        if self.state.shutting_down:
            return

        capture_invalidated = self.state.capture_in_progress
        if capture_invalidated:
            self.state.capture_generation += 1
            self.state.capture_in_progress = False
            self._capture_pending = False
            self._capture_invalidated_on_resume = True

        if self.state.playback is PlaybackState.SPEAKING:
            active = self.state.speech_generation
            if self._speech_worker is not None:
                self._speech_worker.cancel_active(active)

            self.state.speech_generation += 1
            self.state.playback = PlaybackState.STOPPED

        self._ensure_tray_visible()

        restored = (
            self._hotkeys is not None
            and bool(self._hotkeys.reregister())
        )

        if not restored:
            self._show_status(user_message(UserError.HOTKEY_CONFLICT))

        if capture_invalidated:
            self.state.capture_in_progress = True

        hotkey = "unavailable"
        if self._hotkeys is not None:
            spec = getattr(self._hotkeys, "capture_spec", None)
            if spec is not None:
                hotkey = getattr(spec, "canonical", "unavailable")

        self._log_info(
            "system resume playback=%s hotkey=%s"
            % (self.state.playback.name, hotkey)
        )

    def _request_capture(self) -> None:
        if self.state.playback is PlaybackState.SPEAKING:
            self._stop_speech()
            self._capture_replaced_speech = True
        self.state.capture_generation += 1
        generation = self.state.capture_generation
        if self.state.capture_in_progress:
            self._capture_pending = True
            self._capture_invalidated_on_resume = False
            return
        self._start_capture(generation)

    def _start_capture(self, generation: int) -> None:
        self.state.capture_in_progress = True

        def worker() -> None:
            try:
                result = self._capture()
            except Exception as error:
                log_exception_safe(
                    _LOGGER,
                    "capture failed",
                    error,
                    stage="capture_worker",
                )
                result = CaptureResult(CaptureStatus.ACCESS_ERROR, detail=str(error))
            log_capture_result(
                _LOGGER,
                result.status.name,
                len(result.text) if result.text is not None else 0,
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
        if not isinstance(completion, CaptureCompletion):
            return
        generation, result = completion.generation, completion.result
        if not isinstance(result, CaptureResult):
            return
        if generation != self.state.capture_generation:
            if self._capture_pending:
                self.state.capture_in_progress = False
                self._capture_pending = False
                self._start_capture(self.state.capture_generation)
            elif self._capture_invalidated_on_resume:
                self.state.capture_in_progress = False
                self._capture_invalidated_on_resume = False
            return
        self.state.capture_in_progress = False
        if (
            command.kind is CommandKind.CAPTURE_SUCCEEDED
            and result.status is CaptureStatus.SUCCESS
            and result.text is not None
        ):
            self.state.last_text = result.text
            self._capture_replaced_speech = False
            self.state.speech_generation += 1
            self.state.playback = PlaybackState.SPEAKING
            if self._speech_worker is not None:
                self._speech_worker.submit(
                    SpeechRequest(self.state.speech_generation, result.text)
                )
        else:
            if self._capture_replaced_speech:
                self.state.playback = PlaybackState.STOPPED
            if result.status is CaptureStatus.ACCESS_ERROR:
                self._show_status(user_message(UserError.CLIPBOARD))
            else:
                try:
                    self._show_notification("No text selected")
                except Exception as error:
                    _LOGGER.error(
                        "Piper tray notification could not be shown: %s", error
                    )

    def _stop_speech(self) -> None:
        if self.state.playback is not PlaybackState.SPEAKING:
            return
        generation = self.state.speech_generation
        if self._speech_worker is not None:
            self._speech_worker.cancel_active(generation)
        self.state.speech_generation += 1
        self.state.playback = PlaybackState.STOPPED

    def _handle_voice_switch(self, event: object) -> None:
        if not isinstance(event, VoiceSwitchEvent):
            return
        if event.generation != self.state.voice_generation:
            return
        if not event.success:
            self._log_error("Selected Piper voice could not be loaded: %s" % event.error)
            self._show_status(user_message(UserError.VOICE_LOAD_REPLACEMENT))
            return
        if event.model_path is None or event.voice is None or self._voice_manager is None:
            return
        self.install_voice(event.model_path, event.voice, persist=True)

    def _replay(self) -> None:
        if (
            self.state.shutting_down
            or self.state.capture_in_progress
            or self.state.last_text is None
        ):
            return
        if self.state.playback is PlaybackState.SPEAKING:
            if self._speech_worker is not None:
                self._speech_worker.cancel_active(self.state.speech_generation)
        self.state.speech_generation += 1
        self.state.playback = PlaybackState.SPEAKING
        if self._speech_worker is not None:
            self._speech_worker.submit(
                SpeechRequest(self.state.speech_generation, self.state.last_text)
            )

    def _handle_worker_event(self, event: object) -> None:
        if not isinstance(event, SpeechEvent):
            return
        if self.state.shutting_down:
            return
        if event.generation != self.state.speech_generation:
            return
        if event.kind is SpeechEventKind.STARTED:
            self.state.playback = PlaybackState.SPEAKING
        elif event.kind is SpeechEventKind.FINISHED:
            self.state.playback = PlaybackState.IDLE
        elif event.kind is SpeechEventKind.CANCELLED:
            self.state.playback = PlaybackState.STOPPED
        elif event.kind is SpeechEventKind.FAILED:
            self.state.playback = PlaybackState.STOPPED
            if event.failure_phase == "synthesis":
                self._show_status(user_message(UserError.SYNTHESIS))
            else:
                self._show_status(user_message(UserError.PLAYBACK))

    def _begin_shutdown(self) -> None:
        if self.state.shutting_down:
            return

        self.state.shutting_down = True
        if self.state.capture_in_progress:
            self.state.capture_generation += 1
            self.state.capture_in_progress = False
            self._capture_pending = False
        if self.state.playback is PlaybackState.SPEAKING:
            active = self.state.speech_generation
            if self._speech_worker is not None:
                self._speech_worker.cancel_active(active)
        self.state.speech_generation += 1
        self.state.playback = PlaybackState.SHUTTING_DOWN

    def request_hotkey_change(self, requested: str) -> bool:
        if self._hotkeys is None:
            self._show_status("Hotkey settings are not available.")
            return False
        try:
            candidate = parse_hotkey(requested)
        except ValueError:
            self._show_status(user_message(UserError.HOTKEY_INVALID))
            return False
        current = self.state.settings
        if current is None or self._save_settings is None:
            self._show_status("Hotkey settings could not be saved.")
            return False
        if not self._hotkeys.rebind(candidate):
            self._show_status(user_message(UserError.HOTKEY_CONFLICT))
            return False
        next_settings = replace(current, hotkey=candidate.canonical)
        try:
            self._save_settings(next_settings)
        except (OSError, ValueError) as error:
            self._log_error("Could not save Piper hotkey settings: %s" % error)
            rollback_succeeded = False
            try:
                rollback_succeeded = bool(
                    self._hotkeys.rebind(parse_hotkey(current.hotkey))
                )
            except (OSError, ValueError):
                pass
            if rollback_succeeded:
                self._show_status("Piper hotkey settings could not be saved.")
            else:
                self._log_error("Could not restore the previous Piper hotkey")
                self._show_status(
                    "Piper hotkey settings could not be saved, and the previous "
                    "hotkey could not be restored."
                )
            return False
        self.state.settings = next_settings
        return True
