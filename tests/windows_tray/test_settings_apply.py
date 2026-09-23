import json
from pathlib import Path

import pytest

from piper.windows_tray.controller import Controller, KokoroStartupState
from piper.windows_tray.backend_manager import BackendCandidate, BackendManager
from piper.windows_tray.commands import Command, CommandKind
from piper.windows_tray.settings import TraySettings, save_settings


class FakeHotkeys:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.candidates = []

    def rebind(self, candidate):
        self.candidates.append(candidate)
        return self.results.pop(0) if self.results else True

    def prepare_rebind(self, candidate):
        self.candidates.append(candidate)
        return self.results.pop(0) if self.results else True

    def commit_rebind(self):
        return True

    def rollback_rebind(self):
        return True


class TransactionalFakeHotkeys(FakeHotkeys):
    def __init__(self, prepare=True, commit=True, rollback=True):
        super().__init__()
        self.prepare_result = prepare
        self.commit_result = commit
        self.rollback_result = rollback
        self.prepared = []
        self.calls = []

    def prepare_rebind(self, candidate):
        self.calls.append("prepare")
        self.prepared.append(candidate)
        return self.prepare_result

    def commit_rebind(self):
        self.calls.append("commit")
        return self.commit_result

    def rollback_rebind(self):
        self.calls.append("rollback")
        return self.rollback_result


def make_controller(settings=None, hotkeys=None, save_settings=None):
    backend_manager = BackendManager(
        object(),
        lambda: None,
        lambda engine, voice_id: BackendCandidate(engine, voice_id, object()),
    )
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
        backend_manager=backend_manager,
    )


def apply_settings(
    controller,
    hotkey,
    pitch_text,
    speed_text,
    piper_voice_path=None,
    engine="Piper",
    kokoro_voice="af_heart",
):
    return controller.apply_settings(
        engine,
        hotkey,
        pitch_text,
        speed_text,
        piper_voice_path,
        kokoro_voice,
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

    result = apply_settings(
        controller,
        hotkey="not-a-hotkey",
        pitch_text="101",
        speed_text="-51",
        piper_voice_path=Path("new.onnx"),
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

    result = apply_settings(
        controller,
        hotkey="alt+backtick", piper_voice_path=None, **values
    )

    assert result.applied is True


@pytest.mark.parametrize("value", ["", "abc", "nan", "inf", "101", "-51"])
@pytest.mark.parametrize("field", ["pitch", "speed"])
def test_apply_settings_rejects_invalid_percent_text(field, value):
    controller = make_controller()
    values = {"pitch_text": "26", "speed_text": "0"}
    values[f"{field}_text"] = value

    result = apply_settings(
        controller,
        hotkey="alt+backtick", piper_voice_path=None, **values
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

    controller.configure_runtime(
        load_voice=lambda reference: events.append(("load", reference))
        or (Path(reference), new_voice),
    )
    original_prepare = hotkeys.prepare_rebind

    def recording_prepare(candidate):
        events.append(("prepare", candidate.canonical))
        return original_prepare(candidate)

    hotkeys.prepare_rebind = recording_prepare

    original_commit = hotkeys.commit_rebind

    def recording_commit():
        events.append(("commit",))
        return original_commit()

    hotkeys.commit_rebind = recording_commit

    result = apply_settings(
        controller,
        hotkey="Ctrl + Q",
        pitch_text="-10",
        speed_text="50",
        piper_voice_path=Path("new.onnx"),
    )

    assert result.applied is True
    assert result.errors == ()
    assert result.snapshot == controller.settings_window_snapshot()
    assert [event[0] for event in events] == [
        "load",
        "prepare",
        "save",
        "commit",
    ]
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

    result = apply_settings(
        controller,
        hotkey="Alt + Backtick",
        pitch_text="-10",
        speed_text="50",
        piper_voice_path=None,
    )

    assert result.applied is True
    assert loaded == []
    assert hotkeys.candidates == []
    assert saved == [controller.state.settings]
    assert controller.state.settings.pitch_percent == -10
    assert controller.state.settings.speed_percent == 50


@pytest.mark.parametrize("stale_result", ["success", "failure"])
def test_settings_engine_switch_invalidates_in_flight_kokoro_startup(stale_result):
    tray_statuses = []
    settings = TraySettings(engine="Kokoro", kokoro_voice="af_heart")
    controller = make_controller(
        settings=settings,
        hotkeys=FakeHotkeys(),
        save_settings=lambda _settings: None,
    )
    controller.configure_runtime(set_tray_status=tray_statuses.append)
    statuses = []
    controller.configure_runtime(show_status=statuses.append)
    capture_jobs = []
    controller.configure_runtime(capture_submit=capture_jobs.append)
    controller.begin_kokoro_startup()
    stale_candidate = BackendCandidate("Kokoro", "af_heart", object())

    result = apply_settings(
        controller,
        hotkey=settings.hotkey,
        pitch_text=str(settings.pitch_percent),
        speed_text=str(settings.speed_percent),
        piper_voice_path=None,
        engine="Piper",
    )
    assert result.applied is True

    selected_backend = controller._backend_manager.current()
    assert controller.state.settings.engine == "Piper"
    assert tray_statuses[-1] == "Piper is ready"
    controller.handle(Command(CommandKind.CAPTURE_REQUEST))
    assert len(capture_jobs) == 1
    status_count = len(tray_statuses)

    if stale_result == "success":
        controller.complete_kokoro_startup(stale_candidate, ["af_heart"])
    else:
        controller.fail_kokoro_startup("stale Kokoro startup failure")

    assert controller.state.settings.engine == "Piper"
    assert controller._backend_manager.current() is selected_backend
    assert statuses == []
    if stale_result == "success":
        assert stale_candidate._released is True
    assert len(tray_statuses) == status_count


def test_apply_kokoro_settings_during_startup_does_not_prepare_second_backend():
    settings = TraySettings(engine="Kokoro", kokoro_voice="af_heart")
    saved = []
    controller = make_controller(
        settings=settings,
        hotkeys=FakeHotkeys(),
        save_settings=saved.append,
    )
    preparations = []
    original_prepare = controller._backend_manager.prepare
    controller._backend_manager.prepare = lambda engine, voice: preparations.append(
        (engine, voice)
    ) or original_prepare(engine, voice)
    controller.begin_kokoro_startup()

    result = apply_settings(
        controller,
        hotkey=settings.hotkey,
        pitch_text=str(settings.pitch_percent),
        speed_text=str(settings.speed_percent),
        piper_voice_path=None,
        engine="Kokoro",
    )

    assert result.applied is False
    assert result.error_map() == {
        "engine": "Kokoro is still starting. Wait for startup to finish before applying Kokoro settings."
    }
    assert preparations == []
    assert saved == []
    assert controller.state.settings is settings
    assert controller.kokoro_startup_state is KokoroStartupState.LOADING


def test_voice_load_failure_keeps_all_prior_state_and_skips_rebind_and_save():
    original = TraySettings(voice="old.onnx", hotkey="alt+backtick")
    hotkeys = FakeHotkeys()
    saved = []
    controller = make_controller(
        settings=original, hotkeys=hotkeys, save_settings=saved.append
    )
    controller.set_voice(Path("old.onnx"), object())
    controller.configure_runtime(
        load_voice=lambda _reference: (_ for _ in ()).throw(OSError("bad model"))
    )

    result = apply_settings(
        controller,
        "ctrl+q",
        "26",
        "0",
        Path("new.onnx"),
    )

    assert result.applied is False
    assert result.error_map() == {
        "piper_voice": (
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
    controller = make_controller(
        settings=original, hotkeys=hotkeys, save_settings=saved.append
    )
    controller.set_voice(Path("old.onnx"), old_voice)
    controller.configure_runtime(
        load_voice=lambda _reference: (Path("new.onnx"), new_voice)
    )

    result = apply_settings(
        controller,
        "ctrl+q",
        "26",
        "0",
        Path("new.onnx"),
    )

    assert result.applied is False
    assert result.error_map() == {
        "hotkey": "That hotkey is already in use. Choose another combination."
    }
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

    controller = make_controller(
        settings=original, hotkeys=hotkeys, save_settings=fail_save
    )
    controller.set_voice(Path("old.onnx"), old_voice)
    controller.configure_runtime(
        load_voice=lambda _reference: (Path("new.onnx"), new_voice)
    )

    result = apply_settings(
        controller,
        "ctrl+q",
        "26",
        "0",
        Path("new.onnx"),
    )

    assert result.applied is False
    assert result.error_map() == {"general": "Piper settings could not be saved."}
    assert [candidate.canonical for candidate in hotkeys.candidates] == [
        "ctrl+q",
    ]
    assert controller.state.settings == original
    assert controller.state.voice_path == Path("old.onnx")
    assert controller.state.voice is old_voice


def test_save_failure_reports_when_pending_hotkey_cannot_be_removed():
    hotkeys = TransactionalFakeHotkeys(rollback=False)
    errors = []

    def fail_save(_settings):
        raise OSError("disk full")

    controller = make_controller(hotkeys=hotkeys, save_settings=fail_save)
    controller.configure_runtime(log_error=errors.append)

    result = apply_settings(
        controller,
        "ctrl+q",
        "26",
        "0",
        None,
    )

    assert result.applied is False
    assert result.error_map() == {
        "general": (
            "Settings state is uncertain. Restart Piper Tray before changing "
            "settings again."
        )
    }


def test_save_failure_rolls_back_candidate_without_rebinding_old_hotkey():
    original = TraySettings(voice="old.onnx", hotkey="alt+backtick")
    saved = []
    hotkeys = TransactionalFakeHotkeys()

    def fail_save(_settings):
        raise OSError("disk full")

    controller = make_controller(
        settings=original, hotkeys=hotkeys, save_settings=fail_save
    )

    result = apply_settings(
        controller,
        "ctrl+q",
        "26",
        "0",
        None,
    )

    assert result.applied is False
    assert hotkeys.calls == ["prepare", "rollback"]
    assert controller.state.settings == original
    assert saved == []


def test_commit_failure_restores_old_settings_after_new_settings_were_saved():
    original = TraySettings(voice="old.onnx", hotkey="alt+backtick")
    saved = []
    hotkeys = TransactionalFakeHotkeys(commit=False)

    def record_save(settings):
        saved.append(settings)

    controller = make_controller(
        settings=original, hotkeys=hotkeys, save_settings=record_save
    )

    result = apply_settings(
        controller,
        "ctrl+q",
        "26",
        "0",
        None,
    )

    assert result.applied is False
    assert hotkeys.calls == ["prepare", "commit", "rollback"]
    assert saved == [
        TraySettings(voice="old.onnx", hotkey="ctrl+q"),
        original,
    ]
    assert controller.state.settings == original


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
    controller = make_controller(
        settings=TraySettings(),
        save_settings=lambda settings: save_settings(settings, path),
    )
    controller.state.last_text = "private captured text"

    result = apply_settings(
        controller,
        hotkey="alt+backtick",
        pitch_text="26",
        speed_text="0",
        piper_voice_path=None,
    )

    assert result.applied is True
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert "last_text" not in payload
    assert "private captured text" not in path.read_text(encoding="utf-8")
