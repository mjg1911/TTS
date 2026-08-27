import os
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence, Tuple

from .commands import Command, CommandKind
from .controller import Controller, VOICE_SETUP_ERRORS
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
    ui = None
    logger = None

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

        icon_path = Path(__file__).resolve().parents[1] / "img" / "logo.png"
        tray = TrayIcon(icon_path, controller.enqueue)

        def stop_tray() -> None:
            nonlocal tray_stopped
            if not tray_stopped:
                tray.stop()
                tray_stopped = True

        def close_instance() -> None:
            nonlocal instance_closed
            if not instance_closed:
                instance.close()
                instance_closed = True

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
        )

        instance.start_activation_watch(
            lambda: controller.enqueue(Command(CommandKind.ACTIVATE))
        )
        tray.start()
        ui.root.after(25, pump)
        ui.root.mainloop()
        return 0
    except Exception:
        if logger is not None:
            logger.exception("Piper tray application stopped unexpectedly")
        raise
    finally:
        if tray is not None and not tray_stopped:
            tray.stop()
        if not instance_closed:
            instance.close()
        if ui is not None:
            try:
                ui.root.destroy()
            except Exception:
                pass
