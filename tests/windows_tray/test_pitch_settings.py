from types import SimpleNamespace

import pytest

from piper.windows_tray.commands import Command, CommandKind
from piper.windows_tray.controller import Controller
from piper.windows_tray.settings import TraySettings


def test_controller_persists_valid_pitch_and_updates_current_value() -> None:
    saved = []
    controller = Controller(
        settings=TraySettings(pitch_percent=26),
        save_settings=saved.append,
    )

    assert controller.request_pitch_change(-12.5) is True
    assert controller.current_pitch_percent() == -12.5
    assert saved == [TraySettings(pitch_percent=-12.5)]


@pytest.mark.parametrize("value", [101, -51, "26", True, float("nan")])
def test_invalid_pitch_does_not_replace_or_save_current_settings(value) -> None:
    saved = []
    statuses = []
    controller = Controller(
        settings=TraySettings(pitch_percent=26),
        save_settings=saved.append,
    )
    controller.configure_runtime(show_status=statuses.append)

    assert controller.request_pitch_change(value) is False
    assert controller.current_pitch_percent() == 26.0
    assert saved == []
    assert statuses == ["Pitch must be between -50% and 100%."]


def test_failed_pitch_save_keeps_last_known_good_in_memory() -> None:
    statuses = []

    def fail_save(_settings) -> None:
        raise OSError("disk full")

    controller = Controller(
        settings=TraySettings(pitch_percent=26),
        save_settings=fail_save,
    )
    controller.configure_runtime(show_status=statuses.append)

    assert controller.request_pitch_change(40) is False
    assert controller.current_pitch_percent() == 26.0
    assert statuses == ["Piper pitch settings could not be saved."]


def test_prompt_pitch_explains_preserved_speed_and_returns_float(monkeypatch) -> None:
    import piper.windows_tray.ui as ui_module

    ui = object.__new__(ui_module.TkUi)
    ui.root = object()
    ui._thread_id = __import__("threading").get_ident()
    prompts = []

    monkeypatch.setattr(
        ui_module.simpledialog,
        "askstring",
        lambda title, prompt, **kwargs: prompts.append((title, prompt, kwargs)) or "12.5",
    )

    assert ui.prompt_pitch(26) == 12.5
    assert "speech speed is preserved" in prompts[0][1].lower()
    assert prompts[0][2]["initialvalue"] == "26"


@pytest.mark.parametrize("entered", ["abc", "nan", "101", "-51"])
def test_prompt_pitch_rejects_invalid_input(monkeypatch, entered) -> None:
    import piper.windows_tray.ui as ui_module
    import threading

    ui = object.__new__(ui_module.TkUi)
    ui.root = object()
    ui._thread_id = threading.get_ident()
    errors = []
    monkeypatch.setattr(
        ui_module.simpledialog,
        "askstring",
        lambda *_args, **_kwargs: entered,
    )
    monkeypatch.setattr(
        ui_module.messagebox,
        "showerror",
        lambda title, message, **kwargs: errors.append((title, message, kwargs)),
    )

    assert ui.prompt_pitch(26) is None
    assert errors and "-50%" in errors[0][1] and "100%" in errors[0][1]


def test_configure_pitch_command_uses_current_value_and_persists_choice() -> None:
    saved = []
    seen_current = []
    controller = Controller(
        settings=TraySettings(pitch_percent=26),
        save_settings=saved.append,
    )
    controller.configure_runtime(
        choose_pitch=lambda current: seen_current.append(current) or -20,
    )

    controller.handle(Command(CommandKind.CONFIGURE_PITCH))

    assert seen_current == [26.0]
    assert controller.current_pitch_percent() == -20.0
    assert saved[-1].pitch_percent == -20.0


def test_controller_persists_valid_speed_and_updates_current_value() -> None:
    saved = []
    controller = Controller(settings=TraySettings(), save_settings=saved.append)

    assert controller.request_speed_change(50) is True
    assert controller.current_speed_percent() == 50.0
    assert saved == [TraySettings(speed_percent=50)]


def test_prompt_speed_explains_preserved_pitch_and_returns_float(monkeypatch) -> None:
    import piper.windows_tray.ui as ui_module
    import threading

    ui = object.__new__(ui_module.TkUi)
    ui.root = object()
    ui._thread_id = threading.get_ident()
    prompts = []
    monkeypatch.setattr(
        ui_module.simpledialog,
        "askstring",
        lambda title, prompt, **kwargs: prompts.append((title, prompt, kwargs)) or "12.5",
    )

    assert ui.prompt_speed(0) == 12.5
    assert prompts[0][0] == "Speed settings"
    assert "does not change pitch" in prompts[0][1].lower()
    assert prompts[0][2]["initialvalue"] == "0"


@pytest.mark.parametrize("entered", ["abc", "nan", "101", "-51"])
def test_prompt_speed_rejects_invalid_input(monkeypatch, entered) -> None:
    import piper.windows_tray.ui as ui_module
    import threading

    ui = object.__new__(ui_module.TkUi)
    ui.root = object()
    ui._thread_id = threading.get_ident()
    errors = []
    monkeypatch.setattr(ui_module.simpledialog, "askstring", lambda *_args, **_kwargs: entered)
    monkeypatch.setattr(
        ui_module.messagebox,
        "showerror",
        lambda title, message, **kwargs: errors.append((title, message, kwargs)),
    )

    assert ui.prompt_speed(0) is None
    assert errors and "-50%" in errors[0][1] and "100%" in errors[0][1]


def test_configure_speed_command_uses_current_value_and_persists_choice() -> None:
    saved = []
    seen_current = []
    controller = Controller(
        settings=TraySettings(speed_percent=20),
        save_settings=saved.append,
    )
    controller.configure_runtime(
        choose_speed=lambda current: seen_current.append(current) or -20,
    )

    controller.handle(Command(CommandKind.CONFIGURE_SPEED))

    assert seen_current == [20.0]
    assert controller.current_speed_percent() == -20.0
    assert saved[-1].speed_percent == -20.0


@pytest.mark.parametrize("value", [101, -51, "50", True, float("nan")])
def test_invalid_speed_does_not_replace_or_save_current_settings(value) -> None:
    saved = []
    statuses = []
    controller = Controller(settings=TraySettings(speed_percent=20), save_settings=saved.append)
    controller.configure_runtime(show_status=statuses.append)

    assert controller.request_speed_change(value) is False
    assert controller.current_speed_percent() == 20.0
    assert saved == []
    assert statuses == ["Speed must be between -50% and 100%."]
