from types import SimpleNamespace

import pytest

from piper.turbo_options import ENGINE as TURBO_ENGINE
from piper.windows_tray.settings import TraySettings
from tests.windows_tray.test_app_foundation import _patch_primary_app


@pytest.mark.parametrize("engine", ["Piper", "Chatterbox Nano", TURBO_ENGINE])
def test_model_choice_precedes_loading_and_overrides_saved_engine(monkeypatch, engine):
    events = []
    app, _instance, ui, _tray = _patch_primary_app(monkeypatch, events)
    saved_engine = "Chatterbox Nano" if engine == "Piper" else "Piper"
    monkeypatch.setattr(app, "load_settings", lambda: SimpleNamespace(
        settings=TraySettings(engine=saved_engine), source="loaded"
    ))

    def choose(current):
        assert current == saved_engine
        assert "voice" not in events
        assert "startup.start" not in events
        events.append("choose")
        return engine

    ui.choose_startup_engine = choose
    real_loader = app._load_configured_voice

    def load(settings, dirs):
        assert "choose" in events
        assert settings.engine == engine
        return real_loader(settings, dirs)

    monkeypatch.setattr(app, "_load_configured_voice", load)

    class Startup:
        def __init__(self, prepare, logger, *, engine_label):
            assert engine_label == engine

        def start(self):
            events.append("startup.start")

        def cancel(self):
            pass

    monkeypatch.setattr(app, "BackendStartupCoordinator", Startup)
    ui.root.mainloop = lambda: None
    assert app.run_app([]) == 0
    assert "choose" in events
    assert ("startup.start" in events) == (engine != "Piper")


def test_closing_model_choice_exits_without_loading_or_saving(monkeypatch):
    events = []
    app, _instance, ui, tray = _patch_primary_app(monkeypatch, events)
    ui.choose_startup_engine = lambda _current: None
    saved = []
    monkeypatch.setattr(app, "save_settings", saved.append)

    assert app.run_app([]) == 0
    assert "voice" not in events
    assert "controller" not in events
    assert tray.events == []
    assert saved == []
    assert events.count("instance.close") == 1
    assert "ui.close" in events


@pytest.mark.parametrize("label,engine", [
    ("Piper", "Piper"),
    ("Chatterbox Nano", "Chatterbox Nano"),
    ("Chatterbox Turbo", TURBO_ENGINE),
    (None, None),
    ("close", None),
])
def test_startup_buttons_return_engine_or_cancel(monkeypatch, label, engine):
    import threading
    from piper.windows_tray import ui as ui_module
    from tests.windows_tray.test_settings_window import FakeWidget

    monkeypatch.setattr(ui_module, "recorded_engines", lambda: {"nano", "turbo"})

    class Window(FakeWidget):
        def resizable(self, *args):
            pass

        def wait_visibility(self):
            pass

        def grab_set(self):
            self.grabbed = True

        def bind(self, sequence, callback):
            self.bindings = getattr(self, "bindings", {})
            self.bindings[sequence] = callback

    class Button(FakeWidget):
        def winfo_class(self):
            return "TButton"

        def invoke(self):
            self.kwargs["command"]()

    monkeypatch.setattr(ui_module, "tk", SimpleNamespace(Toplevel=Window))
    monkeypatch.setattr(ui_module, "ttk", SimpleNamespace(
        Frame=FakeWidget, Label=FakeWidget, Button=Button
    ))
    ui = ui_module.TkUi.__new__(ui_module.TkUi)
    ui._thread_id = threading.get_ident()
    ui.root = FakeWidget()
    windows = []

    def interact(window):
        windows.append(window)
        body = window.winfo_children()[0]
        buttons = [child for child in body.winfo_children()
                   if child.winfo_class() == "TButton"]
        assert [button.cget("text") for button in buttons] == [
            "Piper", "Chatterbox Nano", "Chatterbox Turbo"
        ]
        assert window.grabbed
        if label is None:
            window.bindings["<Escape>"](None)
        elif label == "close":
            window.protocols["WM_DELETE_WINDOW"]()
        else:
            next(button for button in buttons if button.cget("text") == label).invoke()

    ui.root.wait_window = interact
    assert ui.choose_startup_engine("Chatterbox Nano") == engine
    assert not windows[0].winfo_exists()


def test_startup_popup_only_lists_piper_without_saved_install_records(monkeypatch):
    import threading
    from piper.windows_tray import ui as ui_module
    from tests.windows_tray.test_settings_window import FakeWidget

    class Window(FakeWidget):
        def resizable(self, *args):
            pass

        def wait_visibility(self):
            pass

        def grab_set(self):
            pass

        def bind(self, sequence, callback):
            self.bindings = getattr(self, "bindings", {})
            self.bindings[sequence] = callback

    class Button(FakeWidget):
        def winfo_class(self):
            return "TButton"

        def invoke(self):
            self.kwargs["command"]()
    monkeypatch.setattr(ui_module, "recorded_engines", lambda: set())
    monkeypatch.setattr(ui_module, "tk", SimpleNamespace(Toplevel=Window))
    monkeypatch.setattr(ui_module, "ttk", SimpleNamespace(
        Frame=FakeWidget, Label=FakeWidget, Button=Button
    ))
    ui = ui_module.TkUi.__new__(ui_module.TkUi)
    ui._thread_id = threading.get_ident()
    ui.root = FakeWidget()
    result = []

    def interact(window):
        body = window.winfo_children()[0]
        buttons = [child for child in body.winfo_children()
                   if child.winfo_class() == "TButton"]
        assert [button.cget("text") for button in buttons] == ["Piper"]
        buttons[0].invoke()

    ui.root.wait_window = interact
    result.append(ui.choose_startup_engine("Chatterbox Nano"))

    assert result == ["Piper"]
