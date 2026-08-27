import os
from pathlib import Path
from typing import Iterable, Optional, Sequence, Tuple

from piper import PiperVoice

from .commands import Command, CommandKind
from .controller import Controller
from .logging_setup import configure_logging, log_path
from .settings import TraySettings, load_settings, save_settings
from .single_instance import InstanceRole, SingleInstance
from .tray_icon import TrayIcon
from .ui import TkUi
from .voice_config import load_voice_candidate, resolve_voice_reference


def _voice_data_dirs() -> Iterable[Path]:
    local_appdata = os.environ.get("LOCALAPPDATA")
    directories = [Path.cwd()]
    if local_appdata:
        directories.append(Path(local_appdata) / "Piper")
    return directories


def _load_configured_voice(
    settings: TraySettings, data_dirs: Iterable[Path]
) -> Tuple[Path, PiperVoice]:
    model_path = resolve_voice_reference(settings.voice, data_dirs)
    return model_path, PiperVoice.load(model_path)


def _persist_voice(settings: TraySettings, model_path: Path) -> None:
    save_settings(
        TraySettings(
            voice=str(model_path),
            hotkey=settings.hotkey,
            log_level=settings.log_level,
        )
    )


def run_app(argv: Optional[Sequence[str]] = None) -> int:
    del argv

    instance = SingleInstance()
    if instance.acquire() is InstanceRole.SECONDARY:
        instance.close()
        return 0

    settings_result = load_settings()
    logger = configure_logging(settings_result.settings.log_level)
    ui = TkUi()
    controller = Controller()
    data_dirs = tuple(_voice_data_dirs())
    settings = settings_result.settings
    tray = None
    tray_stopped = False

    try:
        try:
            current_path, current_voice = _load_configured_voice(settings, data_dirs)
        except Exception as error:
            logger.warning("Configured voice could not be loaded: %s", error)
            selected = ui.choose_voice_model()
            if selected is None:
                logger.error("No Piper voice model selected")
                ui.close()
                instance.close()
                return 1
            try:
                current_path, current_voice = load_voice_candidate(
                    str(selected), data_dirs
                )
            except Exception as candidate_error:
                logger.error("Selected Piper voice could not be loaded: %s", candidate_error)
                ui.show_status("The selected Piper voice model could not be loaded.")
                ui.close()
                instance.close()
                return 1
            _persist_voice(settings, current_path)

        icon_path = Path(__file__).resolve().parents[1] / "img" / "logo.png"
        tray = TrayIcon(icon_path, controller.enqueue)

        def pump() -> None:
            nonlocal current_path, current_voice, settings, tray_stopped
            command = controller.drain_once()
            if command is not None:
                if command.kind is CommandKind.ACTIVATE:
                    ui.show_status("Piper is already running.")
                elif command.kind is CommandKind.OPEN_LOG:
                    os.startfile(log_path().parent)
                elif command.kind is CommandKind.CONFIGURE_VOICE:
                    selected = ui.choose_voice_model()
                    if selected is not None:
                        try:
                            candidate_path, candidate_voice = load_voice_candidate(
                                str(selected), data_dirs
                            )
                        except Exception as error:
                            logger.error("Selected Piper voice could not be loaded: %s", error)
                            ui.show_status(
                                "The selected Piper voice model could not be loaded."
                            )
                        else:
                            current_path = candidate_path
                            current_voice = candidate_voice
                            settings = TraySettings(
                                voice=str(current_path),
                                hotkey=settings.hotkey,
                                log_level=settings.log_level,
                            )
                            save_settings(settings)
                elif command.kind is CommandKind.EXIT:
                    tray.stop()
                    tray_stopped = True
                    instance.close()
                    ui.root.quit()

            if not controller.state.shutting_down:
                ui.root.after(25, pump)

        instance.start_activation_watch(
            lambda: controller.enqueue(Command(CommandKind.ACTIVATE))
        )
        tray.start()
        ui.root.after(25, pump)
        ui.root.mainloop()
        return 0
    except Exception:
        logger.exception("Piper tray application stopped unexpectedly")
        raise
    finally:
        if tray is not None and not tray_stopped:
            tray.stop()
        instance.close()
        try:
            ui.root.destroy()
        except Exception:
            pass
