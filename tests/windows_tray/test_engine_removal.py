from dataclasses import asdict
import json

import pytest

from piper.windows_tray.controller import Controller
from piper.windows_tray.settings import TraySettings, load_settings, save_settings


def test_settings_snapshot_only_exposes_supported_engines():
    snapshot = Controller(settings=TraySettings()).settings_window_snapshot()
    assert not any("kokoro" in field for field in asdict(snapshot))


def test_removed_engine_cannot_be_applied():
    controller = Controller(settings=TraySettings())
    result = controller.apply_settings("Kokoro", "alt+backtick", "26", "0", None)
    assert not result.applied
    assert result.error_map() == {"engine": "Choose Piper or Chatterbox Nano."}


@pytest.mark.parametrize("missing_model", [False, True])
def test_migrated_settings_start_piper_and_recover_missing_model(
    monkeypatch, tmp_path, missing_model
):
    from tests.windows_tray.test_app_foundation import _patch_primary_app
    from tests.windows_tray.test_phase2_capture_flow import FakeHotkeys

    path = tmp_path / "settings.json"
    legacy = asdict(TraySettings(piper_voice="saved.onnx", speed_percent=15))
    legacy.update(engine="Kokoro", kokoro_voice="af_heart")
    path.write_text(json.dumps(legacy), encoding="utf-8")
    app, _instance, ui, _tray = _patch_primary_app(monkeypatch, [])
    monkeypatch.setattr(app, "HotkeyManager", lambda: FakeHotkeys([]))
    monkeypatch.setattr(app, "load_settings", lambda: load_settings(path))
    monkeypatch.setattr(app, "save_settings", lambda settings: save_settings(settings, path))
    controllers = []
    monkeypatch.setattr(
        app, "Controller",
        lambda **kwargs: controllers.append(Controller(**kwargs)) or controllers[-1],
    )
    if missing_model:
        def missing(*args):
            raise FileNotFoundError("missing Piper model")
        monkeypatch.setattr(app, "_load_configured_voice", missing)
        replacement = tmp_path / "replacement.onnx"
        ui.choose_voice_model = lambda: replacement
        monkeypatch.setattr(app, "load_voice_candidate", lambda *args: (replacement, object()))

    def mainloop():
        assert controllers[0].state.settings.engine == "Piper"
        assert controllers[0]._backend_manager.current_identity()[0] == "Piper"
    ui.root.mainloop = mainloop
    assert app.run_app([]) == 0
    assert ui.statuses == ["Kokoro is no longer available. Piper has been selected."]
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["engine"] == "Piper"
    assert persisted["speed_percent"] == 15
    assert persisted["piper_voice"] == (str(replacement) if missing_model else "saved.onnx")
    assert "kokoro_voice" not in persisted
    assert not list(tmp_path.glob("*.corrupt*"))
