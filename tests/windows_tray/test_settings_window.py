from pathlib import Path
from types import SimpleNamespace

import pytest

from piper.windows_tray.controller import SettingsApplyResult, SettingsWindowSnapshot


class FakeVar:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeWidget:
    def __init__(self, parent=None, **kwargs):
        self.parent = parent
        self.kwargs = kwargs
        self.children = []
        self.exists = True
        self.configured = {}
        if parent is not None and hasattr(parent, "children"):
            parent.children.append(self)

    def grid(self, **kwargs):
        self.grid_options = kwargs

    def pack(self, **kwargs):
        self.pack_options = kwargs

    def configure(self, **kwargs):
        self.configured.update(kwargs)

    config = configure

    def destroy(self):
        self.exists = False

    def winfo_exists(self):
        return self.exists

    def lift(self):
        self.lift_calls = getattr(self, "lift_calls", 0) + 1

    def focus_force(self):
        self.focus_calls = getattr(self, "focus_calls", 0) + 1

    def transient(self, parent):
        self.transient_parent = parent

    def protocol(self, name, callback):
        self.protocols = getattr(self, "protocols", {})
        self.protocols[name] = callback

    def title(self, value):
        self.window_title = value

    def columnconfigure(self, *args, **kwargs):
        self.column_options = (args, kwargs)

    def rowconfigure(self, *args, **kwargs):
        self.row_options = (args, kwargs)

    def insert(self, index, value):
        self.inserted = (index, value)

    def delete(self, start, end):
        self.deleted = (start, end)

    def get(self):
        return self.value


class FakeText(FakeWidget):
    def __init__(self, parent=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.value = ""
        self.configured["state"] = kwargs.get("state")

    def insert(self, index, value):
        self.value = value
        super().insert(index, value)

    def delete(self, start, end):
        self.value = ""
        super().delete(start, end)

    def get(self, *args):
        return self.value


class FakeToplevel(FakeWidget):
    def deiconify(self):
        self.deiconify_calls = getattr(self, "deiconify_calls", 0) + 1


def install_fake_tk(monkeypatch, built_frames):
    import piper.windows_tray.settings_window as settings_window

    class FakeLabelFrame(FakeWidget):
        def __init__(self, parent=None, **kwargs):
            super().__init__(parent, **kwargs)
            self.text = kwargs.get("text")
            built_frames.append(self)

    class FakeButton(FakeWidget):
        pass

    class FakeEntry(FakeWidget):
        pass

    class FakeLabel(FakeWidget):
        pass

    fake_tk = SimpleNamespace(
        Toplevel=FakeToplevel,
        StringVar=FakeVar,
        Text=FakeText,
        Misc=object,
    )
    fake_ttk = SimpleNamespace(
        LabelFrame=FakeLabelFrame,
        Frame=FakeWidget,
        Button=FakeButton,
        Entry=FakeEntry,
        Label=FakeLabel,
    )
    monkeypatch.setattr(settings_window, "tk", fake_tk)
    monkeypatch.setattr(settings_window, "ttk", fake_ttk)
    monkeypatch.setattr(settings_window, "choose_voice_model", lambda parent: None)
    return settings_window


def make_snapshot(**overrides):
    values = dict(
        voice_path=Path("C:/voices/alba.onnx"),
        hotkey="alt+backtick",
        pitch_percent=26,
        speed_percent=0,
        last_text="hello world",
    )
    values.update(overrides)
    return SettingsWindowSnapshot(**values)


def test_window_builds_all_five_sections_with_initial_values(monkeypatch):
    built_frames = []
    settings_window = install_fake_tk(monkeypatch, built_frames)
    snapshot = make_snapshot()

    window = settings_window.SettingsWindow(
        parent=object(),
        snapshot=snapshot,
        on_apply=lambda *_args: SettingsApplyResult(True),
        on_close=lambda: None,
        on_speak_text=lambda _text: None,
    )

    assert [frame.text for frame in built_frames] == [
        "Voice model",
        "Last captured text",
        "Hotkey settings",
        "Pitch settings",
        "Speed settings",
    ]
    assert window.hotkey_var.get() == "alt+backtick"
    assert window.pitch_var.get() == "26"
    assert window.speed_var.get() == "0"
    assert window.pending_voice_path is None
    assert window.displayed_voice_path == Path("C:/voices/alba.onnx")
    assert window.last_text_value == "hello world"
    assert window.last_text.configured["state"] == "normal"


def test_window_does_not_become_transient_of_a_withdrawn_root(monkeypatch):
    settings_window = install_fake_tk(monkeypatch, [])

    class WithdrawnRoot(FakeWidget):
        def state(self):
            return "withdrawn"

    window = settings_window.SettingsWindow(
        parent=WithdrawnRoot(),
        snapshot=make_snapshot(),
        on_apply=lambda *_args: SettingsApplyResult(True),
        on_close=lambda: None,
        on_speak_text=lambda _text: None,
    )

    assert not hasattr(window.window, "transient_parent")


def test_apply_failure_keeps_window_open_and_renders_field_errors(monkeypatch):
    settings_window = install_fake_tk(monkeypatch, [])
    result = SettingsApplyResult(
        False,
        (
            ("hotkey", "That hotkey is not valid. Choose another combination."),
            ("pitch", "Pitch must be between -50% and 100%."),
        ),
    )
    window = settings_window.SettingsWindow(
        parent=object(),
        snapshot=make_snapshot(),
        on_apply=lambda *_args: result,
        on_close=lambda: None,
        on_speak_text=lambda _text: None,
    )

    window._apply()

    assert window.window.exists is True
    assert window.error_text("hotkey").startswith("That hotkey")
    assert window.error_text("pitch").startswith("Pitch must")


def test_apply_failure_renders_voice_error_in_voice_section(monkeypatch):
    settings_window = install_fake_tk(monkeypatch, [])
    result = SettingsApplyResult(
        False,
        (("voice", "The selected voice could not be loaded."),),
    )
    window = settings_window.SettingsWindow(
        parent=object(),
        snapshot=make_snapshot(),
        on_apply=lambda *_args: result,
        on_close=lambda: None,
        on_speak_text=lambda _text: None,
    )

    window._apply()

    assert window.window.exists is True
    assert window.error_text("voice") == "The selected voice could not be loaded."
    assert window.voice_error_label.kwargs["textvariable"] is window._error_vars["voice"]


def test_apply_success_closes_window(monkeypatch):
    settings_window = install_fake_tk(monkeypatch, [])
    apply_calls = []
    window = settings_window.SettingsWindow(
        parent=object(),
        snapshot=make_snapshot(),
        on_apply=lambda *args: apply_calls.append(args) or SettingsApplyResult(True),
        on_close=lambda: None,
        on_speak_text=lambda _text: None,
    )
    window.hotkey_var.set("ctrl+q")
    window.pitch_var.set("-10")
    window.speed_var.set("25")
    window.pending_voice_path = Path("new.onnx")

    window._apply()

    assert apply_calls == [("ctrl+q", "-10", "25", Path("new.onnx"))]
    assert window.window.exists is False


def test_cancel_discards_local_edits_without_calling_apply(monkeypatch):
    settings_window = install_fake_tk(monkeypatch, [])
    apply_calls = []
    window = settings_window.SettingsWindow(
        parent=object(),
        snapshot=make_snapshot(),
        on_apply=lambda *args: apply_calls.append(args),
        on_close=lambda: None,
        on_speak_text=lambda _text: None,
    )
    window.hotkey_var.set("ctrl+q")
    window.pending_voice_path = Path("new.onnx")

    window.close()
    window.close()

    assert apply_calls == []
    assert window.window.exists is False


def test_update_last_text_keeps_text_editable_and_refreshes_value(monkeypatch):
    settings_window = install_fake_tk(monkeypatch, [])
    window = settings_window.SettingsWindow(
        parent=object(),
        snapshot=make_snapshot(),
        on_apply=lambda *_args: SettingsApplyResult(True),
        on_close=lambda: None,
        on_speak_text=lambda _text: None,
    )

    window.update_last_text("captured\ntext")

    assert window.last_text_value == "captured\ntext"
    assert window.last_text.value == "captured\ntext"
    assert window.last_text.configured["state"] == "normal"

    window.update_last_text(None)

    assert window.last_text_value is None
    assert window.last_text.value == "No text has been captured yet."
    assert window.last_text.configured["state"] == "normal"


def test_choose_voice_only_stages_selected_path(monkeypatch):
    settings_window = install_fake_tk(monkeypatch, [])
    selected = Path("new.onnx")
    monkeypatch.setattr(settings_window, "choose_voice_model", lambda parent: selected)
    window = settings_window.SettingsWindow(
        parent=object(),
        snapshot=make_snapshot(),
        on_apply=lambda *_args: SettingsApplyResult(True),
        on_close=lambda: None,
        on_speak_text=lambda _text: None,
    )

    window._choose_voice()

    assert window.pending_voice_path == selected
    assert window.displayed_voice_path == Path("C:/voices/alba.onnx")
    assert window.voice_label.configured["text"] == str(selected)


def test_speak_text_forwards_exact_multiline_contents(monkeypatch):
    settings_window = install_fake_tk(monkeypatch, [])
    spoken = []
    window = settings_window.SettingsWindow(
        parent=object(),
        snapshot=make_snapshot(),
        on_apply=lambda *_args: SettingsApplyResult(True),
        on_close=lambda: None,
        on_speak_text=spoken.append,
    )
    window.last_text.value = "First line\nSecond line  "

    window._speak_text()

    assert spoken == ["First line\nSecond line  "]


def test_speak_text_ignores_whitespace_only_contents(monkeypatch):
    settings_window = install_fake_tk(monkeypatch, [])
    spoken = []
    window = settings_window.SettingsWindow(
        parent=object(),
        snapshot=make_snapshot(),
        on_apply=lambda *_args: SettingsApplyResult(True),
        on_close=lambda: None,
        on_speak_text=spoken.append,
    )
    window.last_text.value = " \n\t"

    window._speak_text()

    assert spoken == []


def test_tk_ui_repeated_open_focuses_existing_window(monkeypatch):
    import piper.windows_tray.ui as ui_module

    created = []

    class RecordingWindow:
        def __init__(self, **kwargs):
            self.on_close = kwargs["on_close"]
            self.focus_calls = 0
            created.append(self)

        def focus(self):
            self.focus_calls += 1

        def close(self):
            self.on_close()

        def update_last_text(self, text):
            self.updated = text

    monkeypatch.setattr(ui_module, "SettingsWindow", RecordingWindow)
    ui = object.__new__(ui_module.TkUi)
    ui.root = object()
    ui._thread_id = __import__("threading").get_ident()
    ui._settings_window = None

    ui.open_settings(make_snapshot(), lambda *_args: SettingsApplyResult(True))
    first = created[0]
    ui.open_settings(make_snapshot(), lambda *_args: SettingsApplyResult(True))

    assert len(created) == 1
    assert first.focus_calls == 2


def test_tk_ui_first_open_makes_settings_window_visible(monkeypatch):
    import piper.windows_tray.ui as ui_module

    created = []

    class RecordingWindow:
        def __init__(self, **kwargs):
            self.on_close = kwargs["on_close"]
            self.focus_calls = 0
            created.append(self)

        def focus(self):
            self.focus_calls += 1

    monkeypatch.setattr(ui_module, "SettingsWindow", RecordingWindow)
    ui = object.__new__(ui_module.TkUi)
    ui.root = object()
    ui._thread_id = __import__("threading").get_ident()
    ui._settings_window = None

    ui.open_settings(make_snapshot(), lambda *_args: SettingsApplyResult(True))

    assert len(created) == 1
    assert created[0].focus_calls == 1


def test_tk_ui_reopens_after_close_and_forwards_last_text(monkeypatch):
    import piper.windows_tray.ui as ui_module

    created = []

    class RecordingWindow:
        def __init__(self, **kwargs):
            self.on_close = kwargs["on_close"]
            self.edits = []
            created.append(self)

        def focus(self):
            pass

        def close(self):
            self.on_close()

        def update_last_text(self, text):
            self.updated = text

    monkeypatch.setattr(ui_module, "SettingsWindow", RecordingWindow)
    ui = object.__new__(ui_module.TkUi)
    ui.root = object()
    ui._thread_id = __import__("threading").get_ident()
    ui._settings_window = None

    ui.update_settings_last_text("ignored")
    ui.open_settings(make_snapshot(), lambda *_args: SettingsApplyResult(True))
    ui.update_settings_last_text("new text")
    first = created[0]
    first.close()
    ui.open_settings(make_snapshot(), lambda *_args: SettingsApplyResult(True))

    assert first.updated == "new text"
    assert len(created) == 2
