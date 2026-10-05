"""Cancelled model preparation must not save settings."""

import threading
from pathlib import Path

from tests.windows_tray.test_settings_apply import make_controller


def test_cancel_during_piper_voice_load_keeps_previous_settings():
    saved = []
    cancel = threading.Event()
    controller = make_controller(save_settings=saved.append)
    original = controller.state.settings
    original_backend = controller._backend_manager.current()

    def load_voice(reference):
        cancel.set()
        return Path(reference), object()

    controller.configure_runtime(load_voice=load_voice)
    result = controller.apply_settings(
        "Piper",
        "alt+backtick",
        "26",
        "0",
        Path("new.onnx"),
        cancel_event=cancel,
    )
    assert not result.applied
    assert "cancelled" in result.errors[0][1]
    assert saved == []
    assert controller.state.settings is original
    assert controller._backend_manager.current() is original_backend
