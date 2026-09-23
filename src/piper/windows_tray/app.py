import os
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence, Tuple

from .commands import Command, CommandKind
from .backend_manager import BackendCandidate, BackendManager, BackendPreparationError
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
from piper.kokoro_assets import (
    inspect_kokoro_installation,
    verify_kokoro_installation,
)
from .kokoro_client import KokoroWorkerClient, KokoroWorkerConfig
from .kokoro_payload import ensure_bundled_kokoro_payload
from .kokoro_startup import KokoroStartupCoordinator
from .kokoro_verification import KokoroVerificationCoordinator


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


def _kokoro_root() -> Path:
    return Path(os.environ["LOCALAPPDATA"]) / "Piper" / "Kokoro"


def _inspect_kokoro_installation():
    try:
        return inspect_kokoro_installation(_kokoro_root()), None
    except (FileNotFoundError, OSError, ValueError, KeyError) as error:
        return None, "Kokoro installation is unavailable: %s" % type(error).__name__


def _bundled_kokoro_root() -> Optional[Path]:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root is None:
        return None
    candidate = Path(frozen_root) / "kokoro_payload"
    return candidate if candidate.is_dir() else None


def _prepare_kokoro_installation(logger):
    try:
        install_root = _kokoro_root()
        bundle_root = _bundled_kokoro_root()
        if bundle_root is not None:
            return ensure_bundled_kokoro_payload(bundle_root, install_root), None
        return inspect_kokoro_installation(install_root), None
    except (OSError, ValueError, KeyError) as error:
        logger.warning("Kokoro unavailable error_type=%s", type(error).__name__)
        return None, "Kokoro is unavailable because required installed files could not be found or read."


def _load_configured_voice(
    settings: TraySettings, data_dirs: Iterable[Path]
) -> Tuple[Path, Any]:
    from piper import PiperVoice

    model_path = resolve_voice_reference(settings.piper_voice, data_dirs)
    return model_path, PiperVoice.load(model_path)


def _build_speech_worker(controller: Controller, backend_provider) -> SpeechWorker:
    def player_factory(sample_rate: int):
        if not AudioPlayer.is_available():
            raise RuntimeError("ffplay is not available")
        pitch_percent, speed_percent = controller.current_pitch_and_speed_percent()
        return create_playback_pipeline(sample_rate, pitch_percent, speed_percent)

    return SpeechWorker(
        backend_provider,
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
    backend_manager = None
    backend_stopped = False
    kokoro_startup = None
    kokoro_verification = None
    controller = None
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

    def cancel_kokoro_startup() -> None:
        if kokoro_startup is not None:
            kokoro_startup.cancel()

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
        nonlocal speech_stopped, backend_stopped
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
        if backend_manager is not None and not backend_stopped:
            try:
                backend_manager.shutdown()
            except Exception as error:
                if logger is not None:
                    log_exception_safe(logger, "speech backend stop failed", error, stage="shutdown")
            finally:
                backend_stopped = True

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
        cancel_startup=cancel_kokoro_startup,
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
        kokoro_verification = KokoroVerificationCoordinator(
            lambda: verify_kokoro_installation(_kokoro_root()),
            logger,
        )
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
        piper_voice_started = time.monotonic()
        try:
            try:
                configured_path, configured_voice = _load_configured_voice(
                    settings, data_dirs
                )
            finally:
                logger.info(
                    "startup stage=piper_voice_load duration_seconds=%.3f",
                    max(0.0, time.monotonic() - piper_voice_started),
                )
        except VOICE_SETUP_ERRORS as error:
            logger.warning("Configured voice could not be loaded: %s", error)
            selected = ui.choose_voice_model()
            if selected is None:
                logger.error("No Piper voice model selected")
                return 1
            selected_voice_started = time.monotonic()
            try:
                try:
                    selected_path, selected_voice = load_voice_candidate(
                        str(selected), data_dirs
                    )
                finally:
                    logger.info(
                        "startup stage=piper_voice_selection_load duration_seconds=%.3f",
                        max(0.0, time.monotonic() - selected_voice_started),
                    )
            except VOICE_SETUP_ERRORS as candidate_error:
                logger.error(
                    "Selected Piper voice could not be loaded: %s", candidate_error
                )
                ui.show_status(user_message(UserError.VOICE_LOAD_STARTUP))
                return 1
            try:
                settings = replace(settings, piper_voice=str(selected_path))
                save_settings(settings)
            except (OSError, ValueError):
                return 1
            configured_path, configured_voice = selected_path, selected_voice

        kokoro_installation = None
        kokoro_unavailable_reason = None
        kokoro_preparation_attempted = False

        def prepare_backend(engine: str, voice_id: str) -> BackendCandidate:
            nonlocal kokoro_installation, kokoro_unavailable_reason
            nonlocal kokoro_preparation_attempted
            if engine == "Piper":
                path, voice = _load_configured_voice(
                    replace(settings, piper_voice=voice_id), data_dirs
                )
                return BackendCandidate("Piper", voice_id, voice)
            if engine != "Kokoro":
                raise BackendPreparationError("Kokoro is unavailable")
            if not kokoro_preparation_attempted:
                kokoro_preparation_attempted = True
                kokoro_installation, kokoro_unavailable_reason = (
                    _prepare_kokoro_installation(logger)
                )
            if kokoro_installation is None:
                raise BackendPreparationError("Kokoro is unavailable")
            voice = kokoro_installation.voices.get(voice_id)
            if voice is None:
                raise BackendPreparationError("Unknown Kokoro voice")
            if controller is not None:
                controller.set_kokoro_voice_ids(
                    tuple(sorted(kokoro_installation.voices))
                )
            config = KokoroWorkerConfig(
                executable=kokoro_installation.worker_executable,
                install_root=kokoro_installation.root,
                manifest_sha256=kokoro_installation.manifest_sha256,
                worker_version=kokoro_installation.worker_version,
                kokoro_version=kokoro_installation.kokoro_version,
            )
            client = KokoroWorkerClient(config, voice_id)
            try:
                client.ensure_ready()
            except (OSError, RuntimeError, ValueError) as error:
                client.shutdown()
                raise BackendPreparationError("Kokoro worker is unavailable") from error
            return BackendCandidate("Kokoro", voice_id, client, client.shutdown)

        backend_manager = BackendManager(configured_voice, lambda: None, prepare_backend)
        controller = Controller(
            settings=settings,
            save_settings=save_settings,
            backend_manager=backend_manager,
            kokoro_voice_ids=(),
            kokoro_unavailable_reason=kokoro_unavailable_reason,
        )
        if settings.engine == "Kokoro":
            controller.begin_kokoro_startup()
        controller.set_voice(configured_path, configured_voice)
        codex_monitor = CodexMonitor(
            codex_sessions_dir(),
            controller.enqueue_codex_response,
            controller.enqueue_codex_status,
        )

        voice_manager = VoiceManager(
            controller.state.voice,
            lambda reference: load_voice_candidate(reference, data_dirs),
        )
        speech_worker = _build_speech_worker(controller, backend_manager.acquire)

        clipboard = Win32Clipboard()
        capture = SelectionCapture(clipboard, clipboard.send_ctrl_c)
        hotkeys = HotkeyManager()

        icon_path = Path(__file__).resolve().parents[1] / "img" / "logo.png"
        tray = TrayIcon(icon_path, controller.enqueue)
        if settings.engine == "Kokoro":
            tray.set_status("Kokoro is loading")
        if hasattr(tray, "set_snapshot_provider"):
            tray.set_snapshot_provider(controller.tray_snapshot)

        def pump() -> None:
            if kokoro_startup is not None:
                startup_result = kokoro_startup.take_result()
                if startup_result is not None:
                    for stage, duration in startup_result.stage_durations.items():
                        logger.info(
                            "startup stage=%s duration_seconds=%.3f",
                            stage,
                            duration,
                        )
                    if startup_result.candidate is not None:
                        controller.complete_kokoro_startup(
                            startup_result.candidate, startup_result.voice_ids
                        )
                    else:
                        controller.fail_kokoro_startup(
                            startup_result.unavailable_reason
                            or "Kokoro is unavailable during startup."
                        )
            verification_result = kokoro_verification.take_result()
            if verification_result is not None:
                ui.update_settings_kokoro_verification(
                    verification_result.message
                )
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
            set_tray_status=tray.set_status,
            show_notification=tray.show_notification,
            log_error=logger.error,
            open_log=lambda: os.startfile(log_path().parent),
            open_settings=lambda snapshot: ui.open_settings(
                snapshot,
                controller.apply_settings,
                controller.speak_manual_text,
                kokoro_verification.start,
            ),
            update_settings_last_text=getattr(
                ui, "update_settings_last_text", lambda _text: None
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
        tray_hotkey_started = time.monotonic()
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
            logger.info(
                "startup stage=tray_hotkey_failed duration_seconds=%.3f error_type=%s",
                max(0.0, time.monotonic() - tray_hotkey_started),
                type(error).__name__,
            )
        else:
            logger.info(
                "startup stage=tray_hotkey_ready duration_seconds=%.3f",
                max(0.0, time.monotonic() - tray_hotkey_started),
            )

        if settings.engine == "Kokoro":
            def prepare_startup_candidate(cancel_event, record_timing):
                nonlocal kokoro_installation, kokoro_unavailable_reason
                nonlocal kokoro_preparation_attempted
                kokoro_installation, kokoro_unavailable_reason = record_timing(
                    "kokoro_asset_preparation",
                    lambda: _prepare_kokoro_installation(logger),
                )
                kokoro_preparation_attempted = True
                if kokoro_installation is None:
                    raise RuntimeError(kokoro_unavailable_reason or "Kokoro unavailable")
                voice = kokoro_installation.voices.get(settings.kokoro_voice)
                if voice is None:
                    raise RuntimeError("Kokoro voice is unavailable")
                config = KokoroWorkerConfig(
                    executable=kokoro_installation.worker_executable,
                    install_root=kokoro_installation.root,
                    manifest_sha256=kokoro_installation.manifest_sha256,
                    worker_version=kokoro_installation.worker_version,
                    kokoro_version=kokoro_installation.kokoro_version,
                )
                client = KokoroWorkerClient(config, settings.kokoro_voice)
                cancel_event.register_cancel_cleanup(client.shutdown)
                try:
                    record_timing(
                        "kokoro_worker_readiness",
                        lambda: client.ensure_ready(cancel_event),
                    )
                except Exception:
                    client.shutdown()
                    raise
                if cancel_event.is_set():
                    client.shutdown()
                    raise RuntimeError("Kokoro startup was cancelled")
                candidate = BackendCandidate(
                    "Kokoro", settings.kokoro_voice, client, client.shutdown
                )
                return candidate, tuple(sorted(kokoro_installation.voices))

            kokoro_startup = KokoroStartupCoordinator(prepare_startup_candidate, logger)
            kokoro_startup.start()

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
                ui.close()
            except Exception:
                pass
