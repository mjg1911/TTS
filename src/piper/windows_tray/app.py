import os
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence, Tuple

from .commands import Command, CommandKind
from .controller import Controller, VOICE_SETUP_ERRORS
from .errors import UserError, user_message
from . import DEFAULT_HOTKEY
from .capture import SelectionCapture
from .clipboard import Win32Clipboard
from .hotkey import parse_hotkey
from .hotkey_service import HotkeyManager
from .logging_setup import (
    configure_logging,
    log_codex_result,
    log_exception_safe,
    log_path,
)
from .lifecycle import TeardownCoordinator
from .power_events import PowerBroadcastListener
from .pitch_playback import create_playback_pipeline
from piper.audio_playback import AudioPlayer
from .speech import SpeechWorker
from .settings import TraySettings, load_settings, save_settings
from .single_instance import InstanceRole, SingleInstance
from .tray_icon import TrayIcon
from .voice_manager import VoiceManager
from .codex_monitor import CodexMonitor, codex_sessions_dir


def TkUi():
    from .ui import TkUi as TkUiClass

    return TkUiClass()


def resolve_voice_reference(reference: str, data_dirs: Iterable[Path]) -> Path:
    from .voice_config import resolve_voice_reference as resolve

    return resolve(reference, data_dirs)


def load_voice_candidate(reference: str, data_dirs: Iterable[Path]):
    from .voice_config import load_voice_candidate as load

    return load(reference, data_dirs)


def _voice_data_dirs() -> Iterable[Path]:
    local_appdata = os.environ.get("LOCALAPPDATA")
    directories = [Path.cwd()]
    if local_appdata:
        directories.append(Path(local_appdata) / "Piper")
    return directories


def _load_configured_voice(
    settings: TraySettings, data_dirs: Iterable[Path]
) -> Tuple[Path, Any]:
    from piper import PiperVoice

    model_path = resolve_voice_reference(settings.voice, data_dirs)
    return model_path, PiperVoice.load(model_path)


def _build_speech_worker(controller: Controller, voice_manager: VoiceManager) -> SpeechWorker:
    def player_factory(sample_rate: int):
        if not AudioPlayer.is_available():
            raise RuntimeError("ffplay is not available")
        pitch_percent, speed_percent = controller.current_pitch_and_speed_percent()
        return create_playback_pipeline(sample_rate, pitch_percent, speed_percent)

    return SpeechWorker(
        voice_manager.current,
        controller.enqueue_worker_event,
        player_factory,
    )


def run_app(
    argv: Optional[Sequence[str]] = None,
    *,
    debug: bool = False,
) -> int:
    del argv

    instance = SingleInstance()
    instance_closed = False
    tray = None
    tray_stopped = False
    hotkeys = None
    hotkeys_stopped = False
    speech_worker = None
    speech_stopped = False
    power_listener = None
    power_stopped = False
    codex_monitor = None
    codex_stopped = False
    ui = None
    logger = None

    def stop_hotkeys() -> None:
        nonlocal hotkeys_stopped
        if hotkeys is not None and not hotkeys_stopped:
            try:
                hotkeys.stop()
            except Exception as error:
                if logger is not None:
                    logger.error("Piper hotkeys could not be stopped cleanly: %s", error)
            finally:
                hotkeys_stopped = True

    def close_instance() -> None:
        nonlocal instance_closed
        if not instance_closed:
            try:
                instance.close()
            except Exception as error:
                if logger is not None:
                    logger.error("Piper instance could not be closed cleanly: %s", error)
            finally:
                instance_closed = True

    def stop_power_listener() -> None:
        nonlocal power_stopped
        if power_listener is not None and not power_stopped:
            try:
                power_listener.stop()
            except Exception as error:
                if logger is not None:
                    log_exception_safe(
                        logger,
                        "power listener stop failed",
                        error,
                        stage="shutdown",
                    )
            finally:
                power_stopped = True

    def stop_speech() -> None:
        nonlocal speech_stopped
        if speech_worker is not None and not speech_stopped:
            try:
                speech_worker.shutdown()
            except Exception as error:
                if logger is not None:
                    log_exception_safe(
                        logger,
                        "speech worker stop failed",
                        error,
                        stage="shutdown",
                    )
            finally:
                speech_stopped = True

    def stop_codex() -> None:
        nonlocal codex_stopped
        if codex_monitor is not None and not codex_stopped:
            try:
                codex_monitor.stop()
            except Exception as error:
                if logger is not None:
                    log_exception_safe(
                        logger,
                        "codex monitor stop failed",
                        error,
                        stage="shutdown",
                    )
            finally:
                codex_stopped = True

    def stop_tray() -> None:
        nonlocal tray_stopped
        if tray is not None and not tray_stopped:
            try:
                tray.stop()
            except Exception as error:
                if logger is not None:
                    log_exception_safe(
                        logger,
                        "tray stop failed",
                        error,
                        stage="shutdown",
                    )
            finally:
                tray_stopped = True

    def quit_root() -> None:
        if ui is not None:
            ui.root.quit()

    def teardown_failure(stage: str, error: BaseException) -> None:
        if logger is not None:
            log_exception_safe(logger, "shutdown cleanup failed", error, stage=stage)

    def teardown_complete() -> None:
        if logger is not None:
            getattr(logger, "info", lambda *_args: None)("shutdown complete")

    teardown = TeardownCoordinator(
        stop_hotkeys=stop_hotkeys,
        stop_power=stop_power_listener,
        stop_codex=stop_codex,
        stop_speech=stop_speech,
        stop_tray=stop_tray,
        close_instance=close_instance,
        quit_root=quit_root,
        on_failure=teardown_failure,
        on_complete=teardown_complete,
    )

    try:
        if instance.acquire() is InstanceRole.SECONDARY:
            return 0

        settings_result = load_settings()
        effective_level = "DEBUG" if debug else settings_result.settings.log_level
        if debug:
            logger = configure_logging(effective_level, console=True)
        else:
            logger = configure_logging(effective_level)
        ui = TkUi()
        data_dirs = tuple(_voice_data_dirs())
        settings = settings_result.settings
        try:
            capture_hotkey = parse_hotkey(settings.hotkey)
        except ValueError as error:
            logger.warning("Saved Piper hotkey is invalid: %s", error)
            ui.show_status(
                "The saved Piper hotkey was invalid; the default hotkey is being used."
            )
            settings = replace(settings, hotkey=DEFAULT_HOTKEY)
            capture_hotkey = parse_hotkey(DEFAULT_HOTKEY)
        controller = Controller(settings=settings, save_settings=save_settings)
        codex_monitor = CodexMonitor(
            codex_sessions_dir(),
            controller.enqueue_codex_response,
            controller.enqueue_codex_status,
        )

        try:
            configured_path, configured_voice = _load_configured_voice(
                settings, data_dirs
            )
        except VOICE_SETUP_ERRORS as error:
            logger.warning("Configured voice could not be loaded: %s", error)
            selected = ui.choose_voice_model()
            if selected is None:
                logger.error("No Piper voice model selected")
                return 1
            try:
                selected_path, selected_voice = load_voice_candidate(
                    str(selected), data_dirs
                )
            except VOICE_SETUP_ERRORS as candidate_error:
                logger.error(
                    "Selected Piper voice could not be loaded: %s", candidate_error
                )
                ui.show_status(user_message(UserError.VOICE_LOAD_STARTUP))
                return 1
            if not controller.install_voice(selected_path, selected_voice, persist=True):
                return 1
        else:
            controller.set_voice(configured_path, configured_voice)

        voice_manager = VoiceManager(
            controller.state.voice,
            lambda reference: load_voice_candidate(reference, data_dirs),
        )
        speech_worker = _build_speech_worker(controller, voice_manager)

        clipboard = Win32Clipboard()
        capture = SelectionCapture(clipboard, clipboard.send_ctrl_c)
        hotkeys = HotkeyManager()

        icon_path = Path(__file__).resolve().parents[1] / "img" / "logo.png"
        tray = TrayIcon(icon_path, controller.enqueue)
        if hasattr(tray, "set_snapshot_provider"):
            tray.set_snapshot_provider(controller.tray_snapshot)

        def pump() -> None:
            command = controller.drain_once()
            if command is not None:
                controller.handle(command)
            if hasattr(tray, "update_menu"):
                tray.update_menu()
            if not controller.state.shutting_down:
                ui.root.after(25, pump)

        controller.configure_runtime(
            choose_voice=ui.choose_voice_model,
            load_voice=lambda reference: load_voice_candidate(reference, data_dirs),
            voice_manager=voice_manager,
            speech_worker=speech_worker,
            show_status=ui.show_status,
            show_notification=tray.show_notification,
            log_error=logger.error,
            open_log=lambda: os.startfile(log_path().parent),
            open_settings=lambda snapshot: ui.open_settings(
                snapshot,
                controller.apply_settings,
            ),
            ensure_tray_visible=tray.ensure_visible,
            capture=capture.capture,
            log_info=getattr(logger, "info", lambda *_args: None),
            hotkeys=hotkeys,
            choose_hotkey=lambda: ui.prompt_hotkey(
                controller.state.settings.hotkey
                if controller.state.settings is not None
                else settings.hotkey
            ),
            choose_pitch=ui.prompt_pitch,
            choose_speed=ui.prompt_speed,
            show_last_text=ui.show_last_text,
            request_teardown=teardown.run,
            codex_monitor=codex_monitor,
            codex_diagnostic=lambda response_id, character_count, outcome: log_codex_result(
                logger,
                conversation_id=response_id.conversation_id,
                turn_id=response_id.turn_id,
                character_count=character_count,
                outcome=outcome,
            ),
        )
        controller.start_configured_codex_monitoring()
        hotkeys.set_failure_callback(
            lambda error: controller.enqueue(
                Command(CommandKind.HOTKEY_FAILED, str(error))
            )
        )

        instance.start_activation_watch(
            lambda: controller.enqueue(Command(CommandKind.ACTIVATE))
        )
        tray.start()
        try:
            hotkeys.start(
                capture_hotkey,
                on_capture=lambda: controller.enqueue(
                    Command(CommandKind.CAPTURE_REQUEST)
                ),
                on_cancel=lambda: controller.enqueue(
                    Command(CommandKind.CANCEL_REQUEST)
                ),
            )
        except (OSError, ValueError) as error:
            logger.error("Piper hotkeys could not be started: %s", error)
            if getattr(error, "role", "capture") == "cancel":
                ui.show_status(
                    "Piper could not register F8 for cancellation; resolve the "
                    "Windows hotkey conflict."
                )
            else:
                ui.show_status(
                    user_message(UserError.HOTKEY_CONFLICT)
                )
        power_listener = PowerBroadcastListener()
        power_listener.start(
            lambda: controller.enqueue(
                Command(CommandKind.SYSTEM_RESUME)
            )
        )

        def mark_runtime_ready() -> None:
            getattr(logger, "info", lambda *_args: None)(
                "Piper tray runtime ready"
            )
            controller.announce_ready()

        ui.root.after(0, mark_runtime_ready)
        ui.root.after(25, pump)
        ui.root.mainloop()
        return 0
    except Exception:
        if logger is not None:
            logger.exception("Piper tray application stopped unexpectedly")
        raise
    finally:
        teardown.run()
        if ui is not None:
            try:
                ui.root.destroy()
            except Exception:
                pass
