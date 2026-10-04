from types import SimpleNamespace

import pytest

from piper.windows_tray.shortcut_recorder import ShortcutRecorder


class Variable:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class Entry:
    def __init__(self):
        self.bindings = {}
        self.focused = False
        self.unbound = []
        self.state = "normal"

    def cget(self, option):
        assert option == "state"
        return self.state

    def bind(self, sequence, callback, add=None):
        binding_id = f"{sequence}-{len(self.bindings)}"
        self.bindings[sequence] = (binding_id, callback, add)
        return binding_id

    def unbind(self, sequence, binding_id=None):
        self.unbound.append((sequence, binding_id))

    def focus_set(self):
        self.focused = True


def event(keysym, state=0):
    return SimpleNamespace(keysym=keysym, state=state)


def make_recorder(value="alt+backtick"):
    entry = Entry()
    variable = Variable(value)
    status = Variable("")
    recorder = ShortcutRecorder(entry, variable, status)
    return recorder, entry, variable, status


def test_start_records_modifier_combo_and_finishes_with_canonical_binding():
    recorder, entry, variable, status = make_recorder()

    recorder.start()
    result = recorder.handle_key(event("q", state=0x4 | 0x1 | 0x20000))

    assert entry.focused
    assert result == "break"
    assert variable.get() == "ctrl+alt+shift+q"
    assert not recorder.is_recording
    assert status.get() == ""


@pytest.mark.parametrize("sequence", ["<Button-1>", "<Return>", "<space>"])
def test_entry_activation_bindings_are_owned_by_recorder(sequence):
    recorder, entry, _variable, _status = make_recorder()

    assert sequence in entry.bindings
    assert not recorder.is_recording


def test_click_activation_starts_recording():
    recorder, entry, _variable, _status = make_recorder()

    result = entry.bindings["<Button-1>"][1](event(""))

    assert result == "break"
    assert recorder.is_recording
    assert entry.focused


@pytest.mark.parametrize("sequence", ["<Button-1>", "<Return>", "<space>"])
def test_disabled_entry_does_not_start_recording(sequence):
    recorder, entry, _variable, _status = make_recorder()
    entry.state = "disabled"

    entry.bindings[sequence][1](event(""))

    assert not recorder.is_recording
    assert not entry.focused


@pytest.mark.parametrize("sequence", ["<Return>", "<space>"])
def test_keyboard_activation_starts_recording_then_invalid_key_stays_recording(
    sequence,
):
    recorder, entry, variable, status = make_recorder("ctrl+q")
    activate = entry.bindings[sequence][1]

    assert activate(event(sequence[1:-1])) == "break"
    assert recorder.is_recording

    assert activate(event(sequence[1:-1])) == "break"
    assert recorder.is_recording
    assert variable.get() == "ctrl+q"
    assert "unsupported key" in status.get()


def test_windows_modifier_is_tracked_from_keypress_and_keyrelease():
    recorder, entry, variable, _status = make_recorder()
    recorder.start()

    press_id, on_press, _ = entry.bindings["<KeyPress>"]
    _release_id, on_release, _ = entry.bindings["<KeyRelease>"]
    on_press(event("Super_L"))
    recorder.handle_key(event("F2"))

    assert variable.get() == "win+f2"
    assert not recorder.is_recording


def test_windows_modifier_release_clears_held_state():
    recorder, entry, variable, _status = make_recorder()
    recorder.start()

    _press_id, on_press, _ = entry.bindings["<KeyPress>"]
    _release_id, on_release, _ = entry.bindings["<KeyRelease>"]
    on_press(event("Super_L"))
    on_release(event("Super_L"))
    recorder.handle_key(event("q"))

    assert variable.get() == "q"


def test_escape_cancels_and_restores_original_binding():
    recorder, _entry, variable, status = make_recorder("ctrl+q")
    recorder.start()

    recorder.handle_key(event("Escape"))

    assert variable.get() == "ctrl+q"
    assert not recorder.is_recording
    assert status.get() == "Shortcut recording cancelled."


def test_reserved_keys_explain_error_and_keep_recording():
    recorder, _entry, variable, status = make_recorder("ctrl+q")
    recorder.start()

    recorder.handle_key(event("F8"))
    assert recorder.is_recording
    assert variable.get() == "ctrl+q"
    assert "F8 is reserved" in status.get()

    recorder.handle_key(event("F12", state=0x4))
    assert recorder.is_recording
    assert variable.get() == "ctrl+q"
    assert "F12 is reserved" in status.get()


def test_backtick_is_saved_as_canonical_key_name():
    recorder, _entry, variable, _status = make_recorder()
    recorder.start()

    recorder.handle_key(event("grave", state=0x20000))

    assert variable.get() == "alt+backtick"
    assert not recorder.is_recording


def test_shifted_digit_records_the_digit_key_instead_of_its_symbol():
    recorder, _entry, variable, _status = make_recorder()
    recorder.start()
    recorder.handle_key(SimpleNamespace(keysym="exclam", keycode=0x31, state=0x1))
    assert variable.get() == "shift+1"
    assert not recorder.is_recording


def test_unsupported_key_keeps_recording_with_explanation():
    recorder, _entry, variable, status = make_recorder("ctrl+q")
    recorder.start()

    recorder.handle_key(event("space"))

    assert recorder.is_recording
    assert variable.get() == "ctrl+q"
    assert "unsupported key" in status.get()


def test_focus_out_cancels_and_restores_original_binding():
    recorder, entry, variable, _status = make_recorder("alt+f2")
    recorder.start()
    focus_out = entry.bindings["<FocusOut>"][1]

    focus_out(event(""))

    assert variable.get() == "alt+f2"
    assert not recorder.is_recording
