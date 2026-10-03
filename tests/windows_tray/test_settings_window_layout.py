"""Real Tk checks for the resizable speech workspace (no audio required)."""

from pathlib import Path
import tkinter as tk

import pytest

from piper.windows_tray.controller import SettingsApplyResult, SettingsWindowSnapshot
from piper.windows_tray.settings_window import SettingsWindow


@pytest.fixture(scope="module")
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk display unavailable: {exc}")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def studio(tk_root):
    root = tk_root
    window = SettingsWindow(
        root,
        SettingsWindowSnapshot(
            voice_path=Path(
                "C:/voices/" + "long-folder/" * 8 + "en_GB-alba-medium.onnx"
            ),
            hotkey="ctrl+shift+q",
            pitch_percent=2,
            speed_percent=-1,
            last_text="First line\nSecond line",
            kokoro_voices=("af_heart", "af_bella"),
        ),
        on_apply=lambda *_: SettingsApplyResult(
            False, (("hotkey", "Choose another shortcut. " * 8),)
        ),
        on_close=lambda: None,
        on_speak_text=lambda _: None,
        on_verify_kokoro=lambda: True,
    )
    root.update()
    yield root, window
    window.close()


def test_small_window_keeps_preview_and_actions_accessible(studio):
    root, window = studio
    window.window.geometry("900x680")
    root.update()
    assert window.last_text.winfo_width() > 250
    assert window.last_text.winfo_height() > 200
    for widget in (window.speak_text_button, window.save_button, window.cancel_button):
        bottom = widget.winfo_rooty() + widget.winfo_height()
        assert bottom <= window.window.winfo_rooty() + window.window.winfo_height()
        assert widget.winfo_viewable()


def test_engine_switch_and_errors_remain_accessible_in_scrollable_settings(studio):
    root, window = studio
    window.window.geometry("900x680")
    window.engine_var.set("Kokoro")
    window._refresh_voice_controls()
    window._apply()
    root.update()
    assert window.kokoro_voice_combo.winfo_viewable()
    assert not window.piper_voice_frame.winfo_viewable()
    assert window.error_text("hotkey").startswith("Choose another shortcut.")
    window.settings_canvas.yview_moveto(1)
    root.update()
    assert (
        window.kokoro_verify_button.winfo_rooty()
        >= window.settings_canvas.winfo_rooty()
    )
    assert (
        window.kokoro_verify_button.winfo_rooty()
        + window.kokoro_verify_button.winfo_height()
        <= window.settings_canvas.winfo_rooty() + window.settings_canvas.winfo_height()
    )
    assert window.last_text.get("1.0", "end-1c") == "First line\nSecond line"


def test_piper_pause_can_be_corrected_after_switching_to_kokoro(studio):
    root, window = studio
    window.sentence_pause_var.set("invalid")
    window.engine_var.set("Kokoro")
    window._refresh_voice_controls()
    window._on_apply = lambda *_: SettingsApplyResult(
        False, (("sentence_pause", "Enter a whole number of milliseconds."),)
    )
    window._apply()
    root.update()
    assert window.pause_frame.winfo_viewable()
    assert window.error_text("sentence_pause").startswith("Enter a whole number")
