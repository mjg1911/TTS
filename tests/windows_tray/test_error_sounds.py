import pytest

from piper.windows_tray.commands import Command, CommandKind
from piper.windows_tray.controller import Controller
from piper.windows_tray.settings import TraySettings


def test_tray_snapshot_exposes_error_sounds_setting() -> None:
    assert Controller().tray_snapshot().error_sounds_enabled is False
    assert (
        Controller(settings=TraySettings(error_sounds=False))
        .tray_snapshot()
        .error_sounds_enabled
        is False
    )
    assert (
        Controller(settings=TraySettings(error_sounds=True))
        .tray_snapshot()
        .error_sounds_enabled
        is True
    )


def test_toggle_error_sounds_saves_before_committing_state() -> None:
    settings = TraySettings(error_sounds=False)
    saved = []
    controller_ref = []

    def save_settings(next_settings: TraySettings) -> None:
        controller = controller_ref[0]
        assert controller.state.settings.error_sounds is False
        saved.append(next_settings)

    controller = Controller(settings=settings, save_settings=save_settings)
    controller_ref.append(controller)

    controller.handle(Command(CommandKind.TOGGLE_ERROR_SOUNDS))

    assert saved == [TraySettings(error_sounds=True)]
    assert controller.state.settings == TraySettings(error_sounds=True)
    assert controller.tray_snapshot().error_sounds_enabled is True


@pytest.mark.parametrize("failure", [OSError("disk"), ValueError("invalid")])
def test_failed_toggle_error_sounds_save_retains_state_and_checkmark(failure) -> None:
    statuses = []
    errors = []
    settings = TraySettings(error_sounds=False)
    controller = Controller(
        settings=settings,
        save_settings=lambda _settings: (_ for _ in ()).throw(failure),
    )
    controller.configure_runtime(show_status=statuses.append, log_error=errors.append)

    controller.handle(Command(CommandKind.TOGGLE_ERROR_SOUNDS))

    assert controller.state.settings == settings
    assert controller.tray_snapshot().error_sounds_enabled is False
    assert errors == ["Could not save Piper error sound settings: %s" % failure]
    assert statuses == ["Piper error sound settings could not be saved."]
