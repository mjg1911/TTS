import os
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence, Tuple

from .commands import Command, CommandKind
from .controller import Controller, VOICE_SETUP_ERRORS
from . import DEFAULT_HOTKEY
from .capture import SelectionCapture
from .clipboard import Win32Clipboard
from .hotkey import parse_hotkey
from .hotkey_service import HotkeyManager
from .logging_setup import configure_logging, log_path
from .settings import TraySettings, load_settings, save_settings
from .single_instance import InstanceRole, SingleInstance
from .tray_icon import TrayIcon


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


def run_app(argv: Optional[Sequence[str]] = None) -> int:
    del argv

    instance = SingleInstance()
    instance_closed = False
    tray = None
    tray_stopped = False
    hotkeys = None
    hotkeys_stopped = False
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
        stop_hotkeys()
        if not instance_closed:
            try:
                instance.close()
            except Exception as error:
                if logger is not None:
                    logger.error("Piper instance could not be closed cleanly: %s", error)
            finally:
                instance_closed = True

    try:
        if instance.acquire() is InstanceRole.SECONDARY:
            instance.close()
            instance_closed = True
            return 0

        settings_result = load_settings()
        logger = configure_logging(settings_result.settings.log_level)
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
                ui.show_status("The selected Piper voice model could not be loaded.")
                return 1
            if not controller.install_voice(selected_path, selected_voice, persist=True):
                return 1
        else:
            controller.set_voice(configured_path, configured_voice)

        clipboard = Win32Clipboard()
        capture = SelectionCapture(clipboard, clipboard.send_ctrl_c)
        hotkeys = HotkeyManager()

        icon_path = Path(__file__).resolve().parents[1] / "img" / "logo.png"
        tray = TrayIcon(icon_path, controller.enqueue)

        def stop_tray() -> None:
            nonlocal tray_stopped
            if not tray_stopped:
                try:
                    tray.stop()
                except Exception as error:
                    if logger is not None:
                        logger.error("Piper tray could not be stopped cleanly: %s", error)
                finally:
                    tray_stopped = True

        def pump() -> None:
            command = controller.drain_once()
            if command is not None:
                controller.handle(command)
            if not controller.state.shutting_down:
                ui.root.after(25, pump)

        controller.configure_runtime(
            choose_voice=ui.choose_voice_model,
            load_voice=lambda reference: load_voice_candidate(reference, data_dirs),
            show_status=ui.show_status,
            log_error=logger.error,
            open_log=lambda: os.startfile(log_path().parent),
            stop_tray=stop_tray,
            close_instance=close_instance,
            quit_root=ui.root.quit,
            capture=capture.capture,
            hotkeys=hotkeys,
            choose_hotkey=lambda: ui.prompt_hotkey(
                controller.state.settings.hotkey
                if controller.state.settings is not None
                else settings.hotkey
            ),
            show_last_text=ui.show_last_text,
        )
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
            ui.show_status("Piper hotkeys could not be started.")
            return 1
        ui.root.after(25, pump)
        ui.root.mainloop()
        return 0
    except Exception:
        if logger is not None:
            logger.exception("Piper tray application stopped unexpectedly")
        raise
    finally:
        if tray is not None and not tray_stopped:
            stop_tray()
        stop_hotkeys()
        close_instance()
        if ui is not None:
            try:
                ui.root.destroy()
            except Exception:
                pass
