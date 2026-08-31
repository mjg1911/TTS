from dataclasses import dataclass
from dataclasses import replace
from enum import Enum, auto
import logging
from queue import Empty, Queue
from pathlib import Path
import threading
from typing import Callable, Optional, Tuple

from .capture import CaptureResult, CaptureStatus
from .codex_history import CodexCompletedResponse, CodexResponseId
from .codex_monitor import CodexMonitorStatus
from .codex_text import prepare_codex_speech
from .commands import Command, CommandKind
from .hotkey import parse_hotkey
from .logging_setup import log_capture_result, log_exception_safe
from .errors import UserError, user_message
from .settings import (
    DEFAULT_PITCH_PERCENT,
    DEFAULT_SPEED_PERCENT,
    TraySettings,
    validate_pitch_percent,
    validate_speed_percent,
)
from .speech import SpeechEvent, SpeechEventKind, SpeechPurpose, SpeechRequest
from .voice_manager import VoiceManager, VoiceSwitchEvent


_LOGGER = logging.getLogger(__name__)
_LAUNCH_WELCOME = "Piper is ready."
_APPROVED_SPOKEN_ERRORS = frozenset(
    {
        UserError.HOTKEY_CONFLICT,
        UserError.HOTKEY_INVALID,
        UserError.NO_TEXT,
        UserError.CLIPBOARD,
    }
)
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
    auxiliary_generation: int = 0
    auxiliary_active_generation: Optional[int] = None
    auxiliary_active_purpose: Optional[SpeechPurpose] = None
    voice_generation: int = 0
    playback: PlaybackState = PlaybackState.IDLE
    shutting_down: bool = False
    settings: Optional[TraySettings] = None
    voice_path: Optional[Path] = None
    voice: Optional[object] = None

    @property
    def auxiliary_active(self) -> bool:
        return self.auxiliary_active_generation is not None

    @auxiliary_active.setter
    def auxiliary_active(self, active: bool) -> None:
        self.auxiliary_active_generation = 0 if active else None


@dataclass(frozen=True)
class CaptureCompletion:
    generation: int
    result: CaptureResult


@dataclass(frozen=True)
class CodexDelivery:
    epoch: int
    response: CodexCompletedResponse


@dataclass(frozen=True)
class CodexStatusDelivery:
    epoch: int
    status: object


@dataclass(frozen=True)
class TraySnapshot:
    can_stop: bool
    can_replay: bool
    has_last_text: bool
    error_sounds_enabled: bool
    codex_enabled: bool


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
        self._codex_diagnostic: Callable[[CodexResponseId, int, str], None] = (
            lambda _response_id, _character_count, _outcome: None
        )
        self._hotkeys = hotkeys
        self._choose_hotkey: Callable[[], Optional[str]] = lambda: None
        self._choose_pitch: Callable[[float], Optional[float]] = lambda _current: None
        self._choose_speed: Callable[[float], Optional[float]] = lambda _current: None
        self._speech_worker = speech_worker
        self._codex_monitor = None
        self._codex_epoch_lock = threading.Lock()
        self._codex_monitor_epoch = 0
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
        choose_pitch: Optional[Callable[[float], Optional[float]]] = None,
        choose_speed: Optional[Callable[[float], Optional[float]]] = None,
        speech_worker: Optional[object] = None,
        voice_manager: Optional[VoiceManager] = None,
        codex_monitor: Optional[object] = None,
        codex_diagnostic: Optional[Callable[[CodexResponseId, int, str], None]] = None,
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
        if choose_pitch is not None:
            self._choose_pitch = choose_pitch
        if choose_speed is not None:
            self._choose_speed = choose_speed
        if speech_worker is not None:
            self._speech_worker = speech_worker
        if voice_manager is not None:
            self._voice_manager = voice_manager
        elif self._voice_manager is None and self.state.voice is not None and load_voice is not None:
            self._voice_manager = VoiceManager(self.state.voice, load_voice)
        if codex_monitor is not None:
            self._codex_monitor = codex_monitor
        if codex_diagnostic is not None:
            self._codex_diagnostic = codex_diagnostic

    @property
    def codex_monitor_epoch(self) -> int:
        with self._codex_epoch_lock:
            return self._codex_monitor_epoch

    def _advance_codex_epoch(self) -> int:
        with self._codex_epoch_lock:
            self._codex_monitor_epoch += 1
            return self._codex_monitor_epoch

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
                can_stop=(
                    self.state.playback is PlaybackState.SPEAKING
                    or self.state.auxiliary_active_generation is not None
                ),
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
                codex_enabled=(
                    self.state.settings.codex_enabled
                    if self.state.settings is not None
                    else False
                ),
            )

    def enqueue_worker_event(self, event: SpeechEvent) -> None:
        """Queue worker output; worker callbacks must not touch controller state."""
        self.enqueue(Command(CommandKind.WORKER_EVENT, event))

    def enqueue_codex_response(self, response: CodexCompletedResponse) -> None:
        with self._codex_epoch_lock:
            epoch = self._codex_monitor_epoch
        self.enqueue(Command(CommandKind.CODEX_RESPONSE, CodexDelivery(epoch, response)))

    def enqueue_codex_status(self, status: object) -> None:
        with self._codex_epoch_lock:
            epoch = self._codex_monitor_epoch
        self.enqueue(Command(CommandKind.CODEX_MONITOR_STATUS, CodexStatusDelivery(epoch, status)))

    def start_configured_codex_monitoring(self) -> bool:
        settings = self.state.settings
        if (
            settings is None
            or not settings.codex_enabled
            or self._codex_monitor is None
            or self.state.shutting_down
        ):
            return False
        self._advance_codex_epoch()
        try:
            self._codex_monitor.start()
        except Exception as error:
            self._log_error(
                "Codex monitor start failed error_type=%s" % type(error).__name__
            )
            self._show_status("Codex monitoring could not be started.")
            return False
        return True

    def _record_codex_outcome(self, response: CodexCompletedResponse, outcome: str) -> None:
        self._codex_diagnostic(response.response_id, len(response.text), outcome)

    def announce_ready(self) -> None:
        if self.state.shutting_down:
            return

        settings = self.state.settings
        if settings is None or settings.error_sounds:
            return

        self._submit_auxiliary(
            _LAUNCH_WELCOME,
            SpeechPurpose.WELCOME,
        )

    def _report_runtime_error(self, error: UserError) -> None:
        if error not in _APPROVED_SPOKEN_ERRORS:
            raise ValueError("runtime error is not approved for tray reporting")

        message = user_message(error)
        if error is not UserError.NO_TEXT:
            self._show_status(message)

        settings = self.state.settings
        if settings is not None and settings.error_sounds:
            try:
                self._submit_auxiliary(message, SpeechPurpose.ERROR)
            except Exception:
                pass

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
        elif command.kind is CommandKind.TOGGLE_CODEX:
            self._toggle_codex()
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
        elif command.kind is CommandKind.CONFIGURE_PITCH:
            requested = command.value
            if requested is None:
                requested = self._choose_pitch(self.current_pitch_percent())
            if requested is not None:
                self.request_pitch_change(requested)
        elif command.kind is CommandKind.CONFIGURE_SPEED:
            requested = command.value
            if requested is None:
                requested = self._choose_speed(self.current_speed_percent())
            if requested is not None:
                self.request_speed_change(requested)
        elif command.kind is CommandKind.CANCEL_REQUEST:
            self._stop_speech()
        elif command.kind is CommandKind.STOP_REQUEST:
            self._stop_speech()
        elif command.kind is CommandKind.REPLAY_REQUEST:
            self._replay()
        elif command.kind is CommandKind.WORKER_EVENT:
            self._handle_worker_event(command.value)
        elif command.kind is CommandKind.CODEX_RESPONSE:
            self._handle_codex_response(command.value)
        elif command.kind is CommandKind.CODEX_MONITOR_STATUS:
            self._handle_codex_status(command.value)
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
            self._show_status("Piper error sound settings could not be saved.")
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

    def _toggle_codex(self) -> bool:
        current = self.state.settings
        if current is None:
            self._show_status("Codex settings are not available.")
            return False
        return self._set_codex_enabled(not current.codex_enabled)

    def _cancel_codex_speech(self) -> None:
        cancel_codex = getattr(self._speech_worker, "cancel_codex", None)
        if cancel_codex is not None:
            cancel_codex()
        if self.state.auxiliary_active_purpose is SpeechPurpose.CODEX:
            self.state.auxiliary_active_purpose = None
            self.state.auxiliary_active_generation = None

    def _handle_codex_response(self, value: object) -> None:
        if not isinstance(value, CodexDelivery):
            return
        settings = self.state.settings
        if (
            self.state.shutting_down
            or settings is None
            or not settings.codex_enabled
            or value.epoch != self.codex_monitor_epoch
        ):
            return
        if self.state.capture_in_progress or self.state.playback is PlaybackState.SPEAKING:
            self._record_codex_outcome(value.response, "skipped_foreground")
            return
        text = prepare_codex_speech(value.response.text)
        if text is None:
            self._record_codex_outcome(value.response, "skipped_empty")
            return
        self.state.auxiliary_generation += 1
        accepted = bool(
            self._speech_worker is not None
            and self._speech_worker.submit(
                SpeechRequest(self.state.auxiliary_generation, text, SpeechPurpose.CODEX)
            )
        )
        self._record_codex_outcome(
            value.response,
            "submitted" if accepted else "skipped_higher_priority",
        )

    def _handle_codex_status(self, value: object) -> None:
        if not isinstance(value, CodexStatusDelivery):
            return
        settings = self.state.settings
        if (
            self.state.shutting_down
            or settings is None
            or not settings.codex_enabled
            or value.epoch != self.codex_monitor_epoch
        ):
            return
        status = value.status
        status_name = getattr(status, "name", str(status))
        self._log_info("codex_monitor status=%s" % status_name)
        if status is CodexMonitorStatus.HISTORY_MISSING:
            self._show_status(
                "Codex history could not be found. Piper will keep trying while Enable Codex is on."
            )
        elif status is CodexMonitorStatus.UNSUPPORTED_FORMAT:
            self._show_status(
                "Codex monitoring is unavailable because this Codex history format is not supported."
            )

    def _set_codex_enabled(self, enabled: bool) -> bool:
        current = self.state.settings
        if current is None:
            return False
        if enabled:
            next_settings = replace(current, codex_enabled=True)
            self.state.settings = next_settings
            self._advance_codex_epoch()
            if self._codex_monitor is not None:
                try:
                    self._codex_monitor.start()
                except Exception as error:
                    self.state.settings = current
                    self._advance_codex_epoch()
                    try:
                        self._codex_monitor.stop()
                    except Exception as stop_error:
                        self._log_error(
                            "Codex monitor rollback stop failed error_type=%s"
                            % type(stop_error).__name__
                        )
                    self._log_error(
                        "Codex monitor start failed error_type=%s"
                        % type(error).__name__
                    )
                    self._show_status("Codex monitoring could not be started.")
                    return False
            try:
                if self._save_settings is None:
                    raise OSError("settings persistence is not configured")
                self._save_settings(next_settings)
            except (OSError, ValueError) as error:
                self.state.settings = current
                self._advance_codex_epoch()
                if self._codex_monitor is not None:
                    try:
                        self._codex_monitor.stop()
                    except Exception as stop_error:
                        self._log_error(
                            "Codex monitor rollback stop failed error_type=%s"
                            % type(stop_error).__name__
                        )
                self._log_error(
                    "Could not save Piper Codex settings error_type=%s"
                    % type(error).__name__
                )
                self._show_status("Piper Codex settings could not be saved.")
                return False
            return True

        self._advance_codex_epoch()
        if self._codex_monitor is not None:
            try:
                self._codex_monitor.stop()
            except Exception as error:
                self._log_error(
                    "Codex monitor stop failed error_type=%s" % type(error).__name__
                )
        self._cancel_codex_speech()
        next_settings = replace(current, codex_enabled=False)
        self.state.settings = next_settings
        try:
            if self._save_settings is None:
                raise OSError("settings persistence is not configured")
            self._save_settings(next_settings)
        except (OSError, ValueError) as error:
            self._log_error(
                "Could not save Piper Codex settings error_type=%s"
                % type(error).__name__
            )
            self._show_status(
                "Codex monitoring is off for this session, but Piper could not save the setting."
            )
            return False
        return True

    def _recover_from_resume(self) -> None:
        if self.state.shutting_down:
            return

        if self._speech_worker is not None:
            self._speech_worker.cancel_auxiliary()
        self.state.auxiliary_active = False
        self.state.auxiliary_active_purpose = None

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

        settings = self.state.settings
        if settings is not None and settings.codex_enabled and self._codex_monitor is not None:
            self._advance_codex_epoch()
            self._cancel_codex_speech()
            try:
                self._codex_monitor.rebaseline()
            except Exception as error:
                self._log_error(
                    "Codex monitor rebaseline failed error_type=%s"
                    % type(error).__name__
                )

        self._ensure_tray_visible()

        restored = (
            self._hotkeys is not None
            and bool(self._hotkeys.reregister())
        )

        if not restored:
            self._report_runtime_error(UserError.HOTKEY_CONFLICT)

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
        self._cancel_codex_speech()
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
                self._report_runtime_error(UserError.CLIPBOARD)
            else:
                self._report_runtime_error(UserError.NO_TEXT)

    def _stop_speech(self) -> None:
        if self._speech_worker is not None:
            self._speech_worker.cancel_auxiliary()
        self.state.auxiliary_active_generation = None
        self.state.auxiliary_active_purpose = None
        if self.state.playback is not PlaybackState.SPEAKING:
            return
        generation = self.state.speech_generation
        if self._speech_worker is not None:
            self._speech_worker.cancel_active(generation)
        self.state.speech_generation += 1
        self.state.playback = PlaybackState.STOPPED

    def _submit_auxiliary(
        self,
        text: str,
        purpose: SpeechPurpose,
    ) -> None:
        if (
            self.state.shutting_down
            or self._speech_worker is None
        ):
            return

        self.state.auxiliary_generation += 1
        self._speech_worker.submit(
            SpeechRequest(
                self.state.auxiliary_generation,
                text,
                purpose,
            )
        )

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
        if event.purpose is not SpeechPurpose.FOREGROUND:
            if event.kind is SpeechEventKind.STARTED:
                self.state.auxiliary_active_generation = event.generation
                self.state.auxiliary_active_purpose = event.purpose
            elif (
                event.generation == self.state.auxiliary_active_generation
                and event.purpose is self.state.auxiliary_active_purpose
                and event.kind in {
                    SpeechEventKind.FINISHED,
                    SpeechEventKind.CANCELLED,
                    SpeechEventKind.FAILED,
                }
            ):
                self.state.auxiliary_active_generation = None
                self.state.auxiliary_active_purpose = None
            if event.purpose is SpeechPurpose.CODEX and event.kind is SpeechEventKind.FAILED:
                self._show_status(
                    user_message(
                        UserError.SYNTHESIS
                        if event.failure_phase == "synthesis"
                        else UserError.PLAYBACK
                    )
                )
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
        self._advance_codex_epoch()
        if self._speech_worker is not None:
            self._speech_worker.cancel_auxiliary()
        self.state.auxiliary_active = False
        self.state.auxiliary_active_purpose = None
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
            self._report_runtime_error(UserError.HOTKEY_INVALID)
            return False
        current = self.state.settings
        if current is None or self._save_settings is None:
            self._show_status("Hotkey settings could not be saved.")
            return False
        if not self._hotkeys.rebind(candidate):
            self._report_runtime_error(UserError.HOTKEY_CONFLICT)
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

    def current_pitch_percent(self) -> float:
        with self._state_lock:
            settings = self.state.settings
            if settings is None:
                return DEFAULT_PITCH_PERCENT
            return settings.pitch_percent

    def current_pitch_and_speed_percent(self) -> Tuple[float, float]:
        with self._state_lock:
            settings = self.state.settings
            if settings is None:
                return DEFAULT_PITCH_PERCENT, DEFAULT_SPEED_PERCENT
            return settings.pitch_percent, settings.speed_percent

    def request_pitch_change(self, value: object) -> bool:
        with self._state_lock:
            current = self.state.settings
            if current is None or self._save_settings is None:
                self._show_status("Piper pitch settings could not be saved.")
                return False
            try:
                pitch_percent = validate_pitch_percent(value)
            except ValueError:
                self._show_status("Pitch must be between -50% and 100%.")
                return False

            next_settings = replace(current, pitch_percent=pitch_percent)
            try:
                self._save_settings(next_settings)
            except (OSError, ValueError) as error:
                self._log_error("Could not save Piper pitch settings: %s" % error)
                self._show_status("Piper pitch settings could not be saved.")
                return False

            self.state.settings = next_settings
            return True

    def current_speed_percent(self) -> float:
        with self._state_lock:
            settings = self.state.settings
            if settings is None:
                return DEFAULT_SPEED_PERCENT
            return settings.speed_percent

    def request_speed_change(self, value: object) -> bool:
        with self._state_lock:
            current = self.state.settings
            if current is None or self._save_settings is None:
                self._show_status("Piper speed settings could not be saved.")
                return False
            try:
                speed_percent = validate_speed_percent(value)
            except ValueError:
                self._show_status("Speed must be between -50% and 100%.")
                return False

            next_settings = replace(current, speed_percent=speed_percent)
            try:
                self._save_settings(next_settings)
            except (OSError, ValueError) as error:
                self._log_error("Could not save Piper speed settings: %s" % error)
                self._show_status("Piper speed settings could not be saved.")
                return False

            self.state.settings = next_settings
            return True
