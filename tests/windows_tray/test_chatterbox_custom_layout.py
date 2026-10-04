"""Real Tk layout for Chatterbox reference options."""

import pytest

from piper.windows_tray.controller import SettingsApplyResult, SettingsWindowSnapshot
from piper.windows_tray.settings_window import SettingsWindow
from tests.windows_tray.test_settings_window_layout import tk_root


@pytest.mark.parametrize(
    "engine", ["Chatterbox Nano", "Chatterbox Multilingual V3 (500M)"]
)
def test_reference_import_remains_accessible_in_small_settings_window(tk_root, engine):
    window = SettingsWindow(
        tk_root,
        SettingsWindowSnapshot(
            engine=engine,
            chatterbox_reference_clip=(
                "C:/Piper/" + "reference" * 10 + "-" + "a" * 32 + ".wav"
            ),
        ),
        on_apply=lambda *_args, **_kwargs: SettingsApplyResult(False),
        on_close=lambda: None,
        on_speak_text=lambda _text: None,
    )
    try:
        window.window.geometry("900x680")
        tk_root.update()
        button = window.import_reference_clip_button
        window._reveal_setting(button)
        tk_root.update()
        assert button.winfo_viewable()
        assert button.winfo_width() >= button.winfo_reqwidth()
        assert button.winfo_rooty() >= window.settings_canvas.winfo_rooty()
        assert button.winfo_rooty() + button.winfo_height() <= (
            window.settings_canvas.winfo_rooty() + window.settings_canvas.winfo_height()
        )
        combo = window.reference_voice_combo
        assert combo.winfo_viewable()
        assert combo.winfo_width() >= 200
        assert combo.winfo_rootx() + combo.winfo_width() <= (
            window.settings_canvas.winfo_rootx() + window.settings_canvas.winfo_width()
        )
        assert not any(
            widget.winfo_class() == "TLabel"
            and str(widget.cget("textvariable")) == str(window.reference_clip_path_var)
            for widget in window.nano_voice_frame.winfo_children()
        )
        assert window.save_button.winfo_viewable()
        assert window.save_button.winfo_rooty() + window.save_button.winfo_height() <= (
            window.window.winfo_rooty() + window.window.winfo_height()
        )
    finally:
        window.close()
