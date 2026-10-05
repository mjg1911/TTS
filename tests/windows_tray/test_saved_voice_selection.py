"""Saved reference voices can be selected, imported, and staged for Save."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from piper.windows_tray.controller import SettingsApplyResult, SettingsWindowSnapshot
from tests.windows_tray.test_settings_window import install_fake_tk, drain_apply


@pytest.fixture
def voice_panel(monkeypatch, tmp_path):
    module = install_fake_tk(monkeypatch, [])
    first, second = tmp_path / "Anna.wav", tmp_path / "Ben.wav"
    first.touch()
    second.touch()
    choices = {"Anna": str(first), "Ben": str(second)}
    monkeypatch.setattr(
        module, "list_reference_voices", lambda current="": dict(choices), raising=False
    )
    window = module.SettingsWindow(
        object(),
        SettingsWindowSnapshot(
            engine="Chatterbox Nano", chatterbox_reference_clip=str(first)
        ),
        lambda *_args: SettingsApplyResult(True),
        lambda: None,
        lambda _: None,
    )
    return module, window, choices


def test_saved_selection_is_restored_in_readonly_dropdown(voice_panel):
    _, window, choices = voice_panel
    assert window.reference_voice_var.get() == "Anna"
    assert tuple(window.reference_voice_combo.cget("values")) == tuple(choices)
    assert window.reference_voice_combo.cget("state") == "readonly"
    assert window.pending_reference_clip is None


def test_selecting_saved_voice_stages_path_and_enables_it(voice_panel):
    _, window, choices = voice_panel
    window.reference_voice_var.set("Ben")
    window._select_reference_voice()
    assert window.pending_reference_clip == choices["Ben"]
    assert window.displayed_reference_clip == choices["Ben"]
    assert window.chatterbox_custom_voice_var.get() is True
    assert "Save" in window.reference_clip_status_var.get()


def test_save_passes_selected_path_then_restores_it_from_snapshot(voice_panel):
    module, window, choices = voice_panel
    calls = []

    class Owner:
        def cancel_nano_settings(self):
            pass

        def apply(self, *_args, **kwargs):
            calls.append(kwargs)
            return SettingsApplyResult(
                True,
                snapshot=SettingsWindowSnapshot(
                    engine="Chatterbox Nano",
                    chatterbox_reference_clip=choices["Ben"],
                    chatterbox_custom_voice_enabled=True,
                ),
            )

    window._on_apply = Owner().apply
    window.reference_voice_var.set("Ben")
    window._select_reference_voice()
    window._apply()
    drain_apply(window)
    assert calls[0]["chatterbox_reference_clip"] == choices["Ben"]
    assert calls[0]["chatterbox_custom_voice_enabled"] is True
    assert window.reference_voice_var.get() == "Ben"
    assert window.pending_reference_clip is None
    assert window.reference_voice_combo.cget("state") == "readonly"


def test_default_voice_toggle_retains_saved_selection(voice_panel):
    _, window, choices = voice_panel
    window.reference_voice_var.set("Ben")
    window._select_reference_voice()
    window.chatterbox_custom_voice_var.set(False)
    window._toggle_saved_voice()
    assert window.pending_reference_clip == choices["Ben"]
    assert window.reference_voice_var.get() == "Ben"
    assert "default voice" in window.reference_clip_status_var.get().lower()


def test_successful_import_refreshes_and_selects_new_voice(
    voice_panel, monkeypatch, tmp_path
):
    module, window, choices = voice_panel
    imported = tmp_path / "Clara.wav"
    imported.touch()
    monkeypatch.setattr(module, "choose_reference_clip", lambda _: Path("source.wav"))

    def do_import(_source):
        choices["Clara"] = str(imported)
        return imported

    monkeypatch.setattr(module, "import_managed_reference_clip", do_import)
    monkeypatch.setattr(
        module.threading, "Thread", lambda target, **_: SimpleNamespace(start=target)
    )
    window._choose_reference_clip()
    assert window.reference_voice_combo.cget("state") == "disabled"
    window.window.callbacks.pop(0)()
    assert window.reference_voice_var.get() == "Clara"
    assert window.pending_reference_clip == str(imported)
    assert tuple(window.reference_voice_combo.cget("values")) == (
        "Anna",
        "Ben",
        "Clara",
    )
    assert window.chatterbox_custom_voice_var.get() is True
    assert window.reference_voice_combo.cget("state") == "readonly"


def test_failed_import_keeps_dropdown_and_current_voice(voice_panel, monkeypatch):
    module, window, _ = voice_panel
    monkeypatch.setattr(module, "choose_reference_clip", lambda _: Path("invalid.wav"))
    monkeypatch.setattr(
        module,
        "import_managed_reference_clip",
        lambda _: (_ for _ in ()).throw(ValueError("Invalid WAV")),
    )
    monkeypatch.setattr(
        module.threading, "Thread", lambda target, **_: SimpleNamespace(start=target)
    )
    window._choose_reference_clip()
    window.window.callbacks.pop(0)()
    assert window.reference_voice_var.get() == "Anna"
    assert window.pending_reference_clip is None
    assert window.reference_voice_combo.cget("state") == "readonly"
    assert "Invalid WAV" in window.error_text("reference_clip")


def test_failed_import_keeps_save_reminder_for_staged_voice(voice_panel, monkeypatch):
    module, window, _ = voice_panel
    window.reference_voice_var.set("Ben")
    window._select_reference_voice()
    monkeypatch.setattr(module, "choose_reference_clip", lambda _: Path("invalid.wav"))
    monkeypatch.setattr(
        module,
        "import_managed_reference_clip",
        lambda _: (_ for _ in ()).throw(ValueError("Invalid WAV")),
    )
    monkeypatch.setattr(
        module.threading,
        "Thread",
        lambda target, **_: SimpleNamespace(start=target),
    )
    window._choose_reference_clip()
    window.window.callbacks.pop(0)()
    assert window.reference_voice_var.get() == "Ben"
    assert "Save" in window.reference_clip_status_var.get()


def test_empty_library_has_clear_placeholder_and_import_action(voice_panel):
    _, window, choices = voice_panel
    choices.clear()
    window._refresh_reference_voices("")
    assert window.reference_voice_var.get() == "No saved voices yet"
    assert window.reference_voice_combo.cget("state") == "disabled"
    assert window.import_reference_clip_button.cget("state") == "normal"


def test_unavailable_saved_voice_stays_selected(voice_panel, tmp_path):
    _, window, choices = voice_panel
    missing = str(tmp_path / "missing.wav")
    choices["Missing (unavailable)"] = missing
    window._refresh_from_snapshot(
        SettingsWindowSnapshot(
            engine="Chatterbox Nano",
            chatterbox_reference_clip=missing,
            chatterbox_custom_voice_enabled=True,
        )
    )
    assert window.reference_voice_var.get() == "Missing (unavailable)"
    assert window.displayed_reference_clip == missing
    assert "unavailable" in window.reference_clip_status_var.get().lower()


def test_library_error_is_visible_and_preserves_current_voice(voice_panel, monkeypatch):
    module, window, choices = voice_panel

    def fail(_current):
        raise ValueError("Piper could not read its saved voices folder.")

    monkeypatch.setattr(module, "list_reference_voices", fail)
    window._refresh_reference_voices(choices["Anna"])
    assert window.displayed_reference_clip == choices["Anna"]
    assert window.reference_voice_var.get()
    assert "could not read" in window.error_text("reference_clip")


def test_selection_is_ignored_while_import_or_apply_is_pending(voice_panel):
    _, window, _ = voice_panel
    original = window.displayed_reference_clip
    window.reference_voice_var.set("Ben")
    window._reference_import_pending = True
    window._select_reference_voice()
    assert window.pending_reference_clip is None
    assert window.displayed_reference_clip == original
    window._reference_import_pending = False
    window._apply_in_progress = True
    window._select_reference_voice()
    assert window.pending_reference_clip is None
