"""Real Tk integration checks for the settings usability controls."""

import pytest
from threading import Event

from tests.windows_tray.test_settings_window_layout import studio, tk_root
from tests.windows_tray.test_settings_window_layout import wait_for_apply
from piper.windows_tray.controller import SettingsApplyResult


def test_speed_slider_updates_saved_percentage_and_readout(studio):
    root, window = studio
    assert float(window.speed_scale.cget("from")) == -50
    assert float(window.speed_scale.cget("to")) == 100
    window.speed_scale.set(25)
    root.update()
    assert float(window.speed_var.get()) == 25
    assert window.speed_value_var.get() == "+25%"


@pytest.mark.parametrize("title", ["Expressiveness", "Voice/style guidance"])
def test_question_mark_reveals_short_help(studio, title):
    root, window = studio
    window.engine_var.set("Chatterbox Multilingual V3 (500M)")
    window._refresh_voice_controls()
    button, explanation = window.help_controls[title]
    root.update()
    assert button.cget("text") == "?"
    assert not explanation.winfo_ismapped()
    button.invoke()
    root.update()
    assert explanation.winfo_ismapped()
    assert 20 < len(explanation.cget("text")) < 220
    button.invoke()
    root.update()
    assert not explanation.winfo_ismapped()


def test_three_footer_actions_fit_at_minimum_size(studio):
    root, window = studio
    window.window.geometry("900x680")
    root.update()
    for button, text in (
        (window.cancel_button, "Cancel"),
        (window.save_button, "Save"),
        (window.save_close_button, "Save & Close"),
    ):
        assert button.cget("text") == text
        assert button.winfo_viewable()
        assert button.winfo_rootx() + button.winfo_width() <= (
            window.window.winfo_rootx() + window.window.winfo_width()
        )


def test_shortcut_entry_records_a_combination(studio):
    root, window = studio
    window.hotkey_var.set("f2")
    window.focus()
    root.update()
    window.shortcut_recorder.start()
    window.shortcut_entry.focus_force()
    root.update()
    # Ctrl + Shift is Tk's standard state mask on Windows.
    window.shortcut_entry.event_generate("<KeyPress>", keysym="q", state=0x5)
    root.update()
    assert window.hotkey_var.get() == "ctrl+shift+q"
    assert not window.shortcut_recorder.is_recording


def test_model_loading_shows_progress_and_keeps_ui_responsive(studio):
    root, window = studio
    started, release = Event(), Event()

    def slow_apply(*_args):
        started.set()
        assert release.wait(2)
        return SettingsApplyResult(True)

    window._on_apply = slow_apply
    window.window.geometry("900x680")
    try:
        window._apply()
        assert started.wait(1)
        processed = []
        root.after(0, lambda: processed.append(True))
        root.update()
        assert processed == [True]
        assert window.apply_progress.winfo_viewable()
        assert "Piper" in window.apply_status_var.get()
        assert str(window.save_button.cget("state")) == "disabled"
        assert str(window.cancel_button.cget("state")) == "normal"
        window.shortcut_recorder.start()
        assert not window.shortcut_recorder.is_recording
    finally:
        release.set()
        wait_for_apply(root, window)
    assert str(window.save_button.cget("state")) == "normal"
