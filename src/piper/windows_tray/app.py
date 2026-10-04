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
from .backend_startup import BackendStartupCoordinator
from piper.multilingual_options import ENGINE as MULTILINGUAL_ENGINE


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


def _nano_root() -> Path:
    return Path(os.environ["APPDATA"]) / "Piper" / "ChatterboxNano"


def _prepare_nano_installation():
    from piper.nano_assets import inspect_nano_installation

    frozen_root = getattr(sys, "_MEIPASS", None)
    bundled = Path(frozen_root) / "nano_payload" if frozen_root else None
    return inspect_nano_installation(
        bundled if bundled is not None and bundled.is_dir() else _nano_root()
    )


def _prepare_nano_backend(
    cancel_event=None, device="cpu", reference_clip=None
) -> BackendCandidate:
    from .nano_client import NanoWorkerClient

    try:
        installation = _prepare_nano_installation()
        if reference_clip is not None:
            from .chatterbox_voice import validate_reference_clip

            reference_clip = str(validate_reference_clip(Path(reference_clip)))
        client_options = {"device": device}
        if reference_clip is not None:
            client_options["reference_clip"] = reference_clip
        client = NanoWorkerClient(installation, **client_options)
        if cancel_event is not None:
            register_cleanup = getattr(cancel_event, "register_cancel_cleanup", None)
            if register_cleanup is not None:
                register_cleanup(client.shutdown)
        try:
            client.ensure_ready(cancel_event)
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("Nano startup was cancelled")
        except Exception:
            client.shutdown()
            raise
        return BackendCandidate("Chatterbox Nano", "default", client, client.shutdown)
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        raise BackendPreparationError("Chatterbox Nano is unavailable") from error


def _prepare_configured_nano_backend(
    settings, cancel_event=None, record_timing=None
) -> BackendCandidate:
    client_options = {}
    if settings.chatterbox_custom_voice_enabled:
        client_options["reference_clip"] = settings.chatterbox_reference_clip

    prepare = lambda: _prepare_nano_backend(
        cancel_event,
        device=settings.chatterbox_device,
        **client_options,
    )
    if record_timing is not None:
        return record_timing("nano_readiness", prepare)
    return prepare()


def _multilingual_root() -> Path:
    return Path(os.environ['APPDATA']) / 'Piper' / 'ChatterboxMultilingual'


def _prepare_multilingual_installation():
    from piper.multilingual_assets import inspect_multilingual_installation

    frozen_root = getattr(sys, '_MEIPASS', None)
    bundled = Path(frozen_root) / 'multilingual_payload' if frozen_root else None
    return inspect_multilingual_installation(
        bundled if bundled is not None and bundled.is_dir() else _multilingual_root()
    )


def _prepare_multilingual_backend(cancel_event=None, *, language='en', exaggeration=0.5, cfg_weight=0.5, reference_clip=None):
    from .multilingual_client import MultilingualWorkerClient

    try:
        installation = _prepare_multilingual_installation()
        if reference_clip is not None:
            from .chatterbox_voice import validate_reference_clip
            reference_clip = str(validate_reference_clip(Path(reference_clip)))
        client = MultilingualWorkerClient(installation, language=language, exaggeration=exaggeration, cfg_weight=cfg_weight, reference_clip=reference_clip)
        if cancel_event is not None:
            register_cleanup = getattr(cancel_event, 'register_cancel_cleanup', None)
            if register_cleanup is not None:
                register_cleanup(client.shutdown)
        try:
            client.ensure_ready(cancel_event)
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError('Multilingual startup was cancelled')
        except Exception:
            client.shutdown()
            raise
        return BackendCandidate(MULTILINGUAL_ENGINE, 'default', client, client.shutdown)
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        raise BackendPreparationError(f'Multilingual V3 is unavailable: {error}') from error


def _prepare_configured_multilingual_backend(settings, cancel_event=None, record_timing=None):
    options = dict(language=settings.multilingual_language, exaggeration=settings.multilingual_exaggeration, cfg_weight=settings.multilingual_cfg_weight)
    if settings.chatterbox_custom_voice_enabled:
        options['reference_clip'] = settings.chatterbox_reference_clip
    prepare = lambda: _prepare_multilingual_backend(cancel_event, **options)
    return record_timing('multilingual_readiness', prepare) if record_timing is not None else prepare()


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

    worker = SpeechWorker(
        backend_provider,
        controller.enqueue_worker_event,
        player_factory,
    )
    set_pause_provider = getattr(worker, "set_sentence_pause_provider", None)
    if set_pause_provider is not None:
        set_pause_provider(controller.current_sentence_pause_ms)
    set_streaming_provider = getattr(
        worker, "set_piper_sentence_streaming_provider", None
    )
    if set_streaming_provider is not None:
        set_streaming_provider(controller.current_piper_sentence_streaming_enabled)
    return worker


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
    nano_startup = None
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
                    logger.error(
                        "Piper hotkeys could not be stopped cleanly: %s", error
                    )
            finally:
                hotkeys_stopped = True

    def cancel_backend_startup() -> None:
        if nano_startup is not None:
            nano_startup.cancel()

    def close_instance() -> None:
        nonlocal instance_closed
        if not instance_closed:
            try:
                instance.close()
            except Exception as error:
                if logger is not None:
                    logger.error(
                        "Piper instance could not be closed cleanly: %s", error
                    )
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
                    log_exception_safe(
                        logger, "speech backend stop failed", error, stage="shutdown"
                    )
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
        cancel_startup=cancel_backend_startup,
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
        migration_notice = getattr(settings_result, "migration_notice", None)
        if migration_notice:
            ui.show_status(migration_notice)
        data_dirs = tuple(_voice_data_dirs())
        settings = settings_result.settings
        selected_engine = ui.choose_startup_engine(settings.engine)
        if selected_engine is None:
            return 0
        settings = replace(settings, engine=selected_engine)
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
                ui.show_startup_status(user_message(UserError.VOICE_LOAD_STARTUP))
                return 1
            try:
                settings = replace(settings, piper_voice=str(selected_path))
                save_settings(settings)
            except (OSError, ValueError):
                return 1
            configured_path, configured_voice = selected_path, selected_voice
            del selected_voice

        def prepare_backend(engine: str, voice_id: str) -> BackendCandidate:
            if engine == "Piper":
                path, voice = _load_configured_voice(
                    replace(settings, piper_voice=voice_id), data_dirs
                )
                return BackendCandidate("Piper", str(path), voice)
            if engine == MULTILINGUAL_ENGINE:
                if voice_id != 'default':
                    raise BackendPreparationError('Unknown Multilingual voice')
                if controller is None:
                    return _prepare_configured_multilingual_backend(settings)
                return _prepare_multilingual_backend(
                    controller.nano_preparation_cancel_event(),
                    reference_clip=controller.nano_preparation_reference_clip(),
                    **controller.multilingual_preparation_options(),
                )
            if engine == "Chatterbox Nano":
                if voice_id != "default":
                    raise BackendPreparationError("Unknown Nano voice")
                preparation_options = {}
                if controller is not None:
                    reference_clip = controller.nano_preparation_reference_clip()
                    if reference_clip is not None:
                        preparation_options["reference_clip"] = reference_clip
                return _prepare_nano_backend(
                    (
                        controller.nano_preparation_cancel_event()
                        if controller is not None
                        else None
                    ),
                    device=(
                        controller.nano_preparation_device()
                        if controller is not None
                        else settings.chatterbox_device
                    ),
                    **preparation_options,
                )
            raise BackendPreparationError("Unknown speech engine")

        backend_manager = BackendManager(
            "Piper",
            str(configured_path),
            configured_voice,
            lambda: None,
            prepare_backend,
        )
        controller = Controller(
            settings=settings,
            save_settings=save_settings,
            backend_manager=backend_manager,
        )
        if settings.engine in ("Chatterbox Nano", MULTILINGUAL_ENGINE):
            controller.begin_nano_startup()
        controller.set_voice(configured_path, configured_voice)
        del configured_voice
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
        if settings.engine in ("Chatterbox Nano", MULTILINGUAL_ENGINE):
            tray.set_status("%s is loading" % settings.engine)
        if hasattr(tray, "set_snapshot_provider"):
            tray.set_snapshot_provider(controller.tray_snapshot)

        def pump() -> None:
            if nano_startup is not None:
                nano_result = nano_startup.take_result()
                if nano_result is not None:
                    for stage, duration in nano_result.stage_durations.items():
                        logger.info(
                            "startup stage=%s duration_seconds=%.3f",
                            stage,
                            duration,
                        )
                    if nano_result.candidate is not None:
                        controller.complete_nano_startup(nano_result.candidate)
                    else:
                        controller.fail_nano_startup(
                            (
                                'Multilingual V3 could not start. Check the model installation '
                                'and NVIDIA CUDA GPU. CPU fallback is disabled.'
                                if settings.engine == MULTILINGUAL_ENGINE
                                else "Chatterbox Nano is unavailable during startup."
                            )
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
            resolve_voice=lambda reference: resolve_voice_reference(
                reference, data_dirs
            ),
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
                ui.show_startup_status(
                    "Piper could not register F8 for cancellation; resolve the "
                    "Windows hotkey conflict."
                )
            else:
                ui.show_startup_status(user_message(UserError.HOTKEY_CONFLICT))
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

        if settings.engine in ("Chatterbox Nano", MULTILINGUAL_ENGINE):

            def prepare_nano_startup(cancel_event, record_timing):
                prepare_configured = (
                    _prepare_configured_multilingual_backend
                    if settings.engine == MULTILINGUAL_ENGINE
                    else _prepare_configured_nano_backend
                )
                candidate = prepare_configured(
                    settings,
                    cancel_event=cancel_event,
                    record_timing=record_timing,
                )
                return candidate, ()

            nano_startup = BackendStartupCoordinator(prepare_nano_startup, logger, engine_label=settings.engine)
            nano_startup.start()

        power_listener = PowerBroadcastListener()
        power_listener.start(
            lambda: controller.enqueue(Command(CommandKind.SYSTEM_RESUME))
        )

        def mark_runtime_ready() -> None:
            getattr(logger, "info", lambda *_args: None)("Piper tray runtime ready")
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
