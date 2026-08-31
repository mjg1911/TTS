import json
from pathlib import Path

import pytest

from piper.windows_tray.controller import Controller
from piper.windows_tray.settings import TraySettings, save_settings


class FakeHotkeys:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.candidates = []

    def rebind(self, candidate):
        self.candidates.append(candidate)
        return self.results.pop(0) if self.results else True


def make_controller(settings=None, hotkeys=None, save_settings=None):
    return Controller(
        settings=settings
        or TraySettings(
            voice="old-voice",
            hotkey="alt+backtick",
            pitch_percent=26,
            speed_percent=0,
        ),
        save_settings=save_settings or (lambda _settings: None),
        hotkeys=hotkeys or FakeHotkeys(),
    )


def test_apply_settings_collects_scalar_errors_before_side_effects():
    loaded = []
    saved = []
    hotkeys = FakeHotkeys()
    controller = make_controller(hotkeys=hotkeys, save_settings=saved.append)
    controller.configure_runtime(
        load_voice=lambda reference: loaded.append(reference)
        or (Path(reference), object())
    )

    result = controller.apply_settings(
        hotkey="not-a-hotkey",
        pitch_text="101",
        speed_text="-51",
        voice_path=Path("new.onnx"),
    )

    assert result.applied is False
    assert result.error_map() == {
        "hotkey": "That hotkey is not valid. Choose another combination.",
        "pitch": "Pitch must be between -50% and 100%.",
        "speed": "Speed must be between -50% and 100%.",
    }
    assert loaded == []
    assert hotkeys.candidates == []
    assert saved == []
    assert controller.state.settings.hotkey == "alt+backtick"


@pytest.mark.parametrize("value", ["-50", "100"])
@pytest.mark.parametrize("field", ["pitch", "speed"])
def test_apply_settings_accepts_percent_boundaries(field, value):
    controller = make_controller()
    values = {"pitch_text": "26", "speed_text": "0"}
    values[f"{field}_text"] = value

    result = controller.apply_settings(
        hotkey="alt+backtick", voice_path=None, **values
    )

    assert result.applied is True


@pytest.mark.parametrize("value", ["", "abc", "nan", "inf", "101", "-51"])
@pytest.mark.parametrize("field", ["pitch", "speed"])
def test_apply_settings_rejects_invalid_percent_text(field, value):
    controller = make_controller()
    values = {"pitch_text": "26", "speed_text": "0"}
    values[f"{field}_text"] = value

    result = controller.apply_settings(
        hotkey="alt+backtick", voice_path=None, **values
    )

    assert result.applied is False
    assert result.error_map() == {
        field: f"{field.title()} must be between -50% and 100%."
    }


def test_apply_settings_loads_voice_before_rebind_and_commits_after_save():
    events = []
    old_voice = object()
    new_voice = object()
    hotkeys = FakeHotkeys([True])
    controller = make_controller(
        hotkeys=hotkeys,
        save_settings=lambda settings: events.append(("save", settings)),
    )
    controller.set_voice(Path("old.onnx"), old_voice)

    class FakeVoiceManager:
        def replace(self, voice):
            events.append(("replace", voice))

    controller.configure_runtime(
        voice_manager=FakeVoiceManager(),
        load_voice=lambda reference: events.append(("load", reference))
        or (Path(reference), new_voice),
    )
    original_rebind = hotkeys.rebind

    def recording_rebind(candidate):
        events.append(("rebind", candidate.canonical))
        return original_rebind(candidate)

    hotkeys.rebind = recording_rebind

    result = controller.apply_settings(
        hotkey="Ctrl + Q",
        pitch_text="-10",
        speed_text="50",
        voice_path=Path("new.onnx"),
    )

    assert result.applied is True
    assert result.errors == ()
    assert result.snapshot == controller.settings_window_snapshot()
    assert [event[0] for event in events] == ["load", "rebind", "save", "replace"]
    assert controller.state.settings == TraySettings(
        voice="new.onnx",
        hotkey="ctrl+q",
        pitch_percent=-10,
        speed_percent=50,
    )
    assert controller.state.voice_path == Path("new.onnx")
    assert controller.state.voice is new_voice


def test_apply_settings_unchanged_voice_and_hotkey_still_saves_scalars():
    loaded = []
    hotkeys = FakeHotkeys()
    saved = []
    controller = make_controller(hotkeys=hotkeys, save_settings=saved.append)
    controller.configure_runtime(load_voice=lambda reference: loaded.append(reference))

    result = controller.apply_settings(
        hotkey="Alt + Backtick",
        pitch_text="-10",
        speed_text="50",
        voice_path=None,
    )

    assert result.applied is True
    assert loaded == []
    assert hotkeys.candidates == []
    assert saved == [controller.state.settings]
    assert controller.state.settings.pitch_percent == -10
    assert controller.state.settings.speed_percent == 50


def test_voice_load_failure_keeps_all_prior_state_and_skips_rebind_and_save():
    original = TraySettings(voice="old.onnx", hotkey="alt+backtick")
    hotkeys = FakeHotkeys()
    saved = []
    controller = make_controller(settings=original, hotkeys=hotkeys, save_settings=saved.append)
    controller.set_voice(Path("old.onnx"), object())
    controller.configure_runtime(load_voice=lambda _reference: (_ for _ in ()).throw(OSError("bad model")))

    result = controller.apply_settings("ctrl+q", "26", "0", Path("new.onnx"))

    assert result.applied is False
    assert result.error_map() == {
        "voice": (
            "The selected voice could not be loaded. "
            "The previous voice is still active."
        )
    }
    assert controller.state.settings == original
    assert controller.state.voice_path == Path("old.onnx")
    assert hotkeys.candidates == []
    assert saved == []


def test_hotkey_conflict_keeps_prior_settings_and_loaded_voice_uncommitted():
    original = TraySettings(voice="old.onnx", hotkey="alt+backtick")
    old_voice = object()
    new_voice = object()
    hotkeys = FakeHotkeys([False])
    saved = []
    controller = make_controller(settings=original, hotkeys=hotkeys, save_settings=saved.append)
    controller.set_voice(Path("old.onnx"), old_voice)
    controller.configure_runtime(load_voice=lambda _reference: (Path("new.onnx"), new_voice))

    result = controller.apply_settings("ctrl+q", "26", "0", Path("new.onnx"))

    assert result.applied is False
    assert result.error_map() == {"hotkey": "That hotkey is already in use. Choose another combination."}
    assert controller.state.settings == original
    assert controller.state.voice_path == Path("old.onnx")
    assert controller.state.voice is old_voice
    assert saved == []


def test_save_failure_restores_old_hotkey_and_keeps_old_voice_and_settings():
    original = TraySettings(voice="old.onnx", hotkey="alt+backtick")
    old_voice = object()
    new_voice = object()
    hotkeys = FakeHotkeys(results=[True, True])

    def fail_save(_settings):
        raise OSError("disk full")

    controller = make_controller(settings=original, hotkeys=hotkeys, save_settings=fail_save)
    controller.set_voice(Path("old.onnx"), old_voice)
    controller.configure_runtime(load_voice=lambda _reference: (Path("new.onnx"), new_voice))

    result = controller.apply_settings("ctrl+q", "26", "0", Path("new.onnx"))

    assert result.applied is False
    assert result.error_map() == {"general": "Piper settings could not be saved."}
    assert [candidate.canonical for candidate in hotkeys.candidates] == [
        "ctrl+q",
        "alt+backtick",
    ]
    assert controller.state.settings == original
    assert controller.state.voice_path == Path("old.onnx")
    assert controller.state.voice is old_voice


def test_save_failure_reports_when_old_hotkey_cannot_be_restored():
    hotkeys = FakeHotkeys(results=[True, False])
    errors = []

    def fail_save(_settings):
        raise OSError("disk full")

    controller = make_controller(hotkeys=hotkeys, save_settings=fail_save)
    controller.configure_runtime(log_error=errors.append)

    result = controller.apply_settings("ctrl+q", "26", "0", None)

    assert result.applied is False
    assert result.error_map() == {
        "general": (
            "Piper settings could not be saved, and the previous hotkey "
            "could not be restored."
        )
    }
    assert errors == [
        "Could not save Piper settings: disk full",
        "Could not restore the previous Piper hotkey",
    ]


def test_settings_window_snapshot_copies_committed_editor_state():
    controller = make_controller()
    controller.state.last_text = "captured"
    controller.state.voice_path = Path("voice.onnx")

    snapshot = controller.settings_window_snapshot()

    assert snapshot.voice_path == Path("voice.onnx")
    assert snapshot.hotkey == "alt+backtick"
    assert snapshot.pitch_percent == 26
    assert snapshot.speed_percent == 0
    assert snapshot.last_text == "captured"


def test_apply_settings_never_persists_last_captured_text(tmp_path):
    path = tmp_path / "settings.json"
    controller = Controller(
        settings=TraySettings(),
        save_settings=lambda settings: save_settings(settings, path),
        hotkeys=FakeHotkeys(),
    )
    controller.state.last_text = "private captured text"

    result = controller.apply_settings(
        hotkey="alt+backtick",
        pitch_text="26",
        speed_text="0",
        voice_path=None,
    )

    assert result.applied is True
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert "last_text" not in payload
    assert "private captured text" not in path.read_text(encoding="utf-8")
