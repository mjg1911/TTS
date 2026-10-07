"""Async save actions for the settings window."""

from threading import Event, get_ident

from tests.windows_tray.test_settings_window import (
    drain_apply,
    install_fake_tk,
    make_snapshot,
)
from piper.windows_tray.controller import SettingsApplyResult


def _window(monkeypatch, callback, on_close=None):
    settings_window = install_fake_tk(monkeypatch, [])
    window = settings_window.SettingsWindow(
        parent=object(),
        snapshot=make_snapshot(),
        on_apply=callback,
        on_close=on_close or (lambda: None),
        on_speak_text=lambda _text: None,
    )
    return window


def test_save_runs_piper_apply_off_ui_thread_and_stays_open(monkeypatch):
    started = Event()
    release = Event()
    ui_thread = get_ident()
    worker_threads = []

    def apply(*_args):
        worker_threads.append(get_ident())
        started.set()
        release.wait(1)
        return SettingsApplyResult(True)

    window = _window(monkeypatch, apply)
    window._apply()

    assert started.wait(1)
    assert worker_threads[0] != ui_thread
    assert window._apply_in_progress
    assert window.save_button.cget("state") == "disabled"
    assert window.save_close_button.cget("state") == "disabled"
    assert window.engine_combo.cget("state") == "disabled"
    assert window.apply_progress.started is True
    assert "Piper" in window.apply_status_var.get()
    release.set()
    drain_apply(window)

    assert window.window.exists is True
    assert window.apply_status_var.get() == "Saved."
    assert window.save_button.cget("state") == "normal"
    assert window.save_close_button.cget("state") == "normal"
    assert window.engine_combo.cget("state") == "readonly"
    assert window.apply_progress.started is False


def test_save_and_close_closes_only_after_success(monkeypatch):
    window = _window(monkeypatch, lambda *_args: SettingsApplyResult(True))

    window._apply(close_after=True)
    drain_apply(window)

    assert window.window.exists is False


def test_failed_save_stays_open_and_restores_busy_controls(monkeypatch):
    result = SettingsApplyResult(False, (("hotkey", "Choose another shortcut."),))
    window = _window(monkeypatch, lambda *_args: result)

    window._apply(close_after=True)
    drain_apply(window)

    assert window.window.exists is True
    assert window.error_text("hotkey") == "Choose another shortcut."
    assert window.apply_status_var.get() == ""


def test_apply_exception_is_shown_and_busy_state_is_cleaned(monkeypatch):
    def fail(*_args):
        raise RuntimeError("unexpected backend failure")

    window = _window(monkeypatch, fail)

    window._apply()
    drain_apply(window)

    assert window.window.exists is True
    assert "unexpected backend failure" in window.error_text("general")
    assert window.apply_status_var.get() == ""


def test_save_success_does_not_replace_editable_preview_text(monkeypatch):
    window = _window(
        monkeypatch,
        lambda *_args: SettingsApplyResult(
            True, snapshot=make_snapshot(speed_percent=25)
        ),
    )
    window.last_text.delete("1.0", "end")
    window.last_text.insert("1.0", "Edited preview")

    window._apply()
    drain_apply(window)

    assert window.last_text.get("1.0", "end-1c") == "Edited preview"
    assert window.speed_value_var.get() == "+25%"


def test_missing_model_disables_save_until_download_is_ready(monkeypatch):
    import piper.windows_tray.model_download_ui as download_ui
    from threading import Event

    settings_window = install_fake_tk(
        monkeypatch, [], real_model_download_panel=True
    )
    monkeypatch.setattr(download_ui, "tk", settings_window.tk)
    monkeypatch.setattr(download_ui, "ttk", settings_window.ttk)
    monkeypatch.setattr(download_ui, "engine_installed", lambda _engine: False)
    download_started, release_download = Event(), Event()

    def download(*_args):
        download_started.set()
        assert release_download.wait(2)
        return "generation"

    monkeypatch.setattr(download_ui, "download_engine", download)
    apply_calls = []
    window = settings_window.SettingsWindow(
        parent=object(),
        snapshot=make_snapshot(engine="Chatterbox Nano"),
        on_apply=lambda *args: apply_calls.append(args) or SettingsApplyResult(True),
        on_close=lambda: None,
        on_speak_text=lambda _text: None,
    )
    panel = window.model_download_panel

    def pump_until(predicate):
        import time
        deadline = time.monotonic() + 2
        while not predicate():
            assert time.monotonic() < deadline
            callbacks, panel.parent.callbacks = (
                getattr(panel.parent, "callbacks", []), []
            )
            for callback in callbacks:
                callback()
            time.sleep(0.001)

    pump_until(lambda: panel.state == "missing")
    assert window.save_button.cget("state") == "disabled"
    assert window.save_close_button.cget("state") == "disabled"

    window._apply()
    assert apply_calls == []
    assert "Download" in window.error_text("engine")

    panel.download_button.invoke()
    assert download_started.wait(1)
    assert panel.state == "downloading"
    assert window.save_button.cget("state") == "disabled"
    assert window.save_close_button.cget("state") == "disabled"
    window._apply()
    assert apply_calls == []
    release_download.set()
    pump_until(lambda: panel.state == "ready")
    assert window.save_button.cget("state") == "normal"
    assert window.save_close_button.cget("state") == "normal"

    window._apply()
    drain_apply(window)
    assert len(apply_calls) == 1


def test_installed_chatterbox_keeps_normal_save_behavior(monkeypatch):
    import piper.windows_tray.model_download_ui as download_ui

    settings_window = install_fake_tk(
        monkeypatch, [], real_model_download_panel=True
    )
    monkeypatch.setattr(download_ui, "tk", settings_window.tk)
    monkeypatch.setattr(download_ui, "ttk", settings_window.ttk)
    monkeypatch.setattr(download_ui, "engine_installed", lambda _engine: True)
    apply_calls = []
    window = settings_window.SettingsWindow(
        parent=object(),
        snapshot=make_snapshot(engine="Chatterbox Turbo (350M)"),
        on_apply=lambda *args: apply_calls.append(args) or SettingsApplyResult(True),
        on_close=lambda: None,
        on_speak_text=lambda _text: None,
    )
    panel = window.model_download_panel

    import time
    deadline = time.monotonic() + 2
    while panel.state != "ready":
        assert time.monotonic() < deadline
        callbacks, panel.parent.callbacks = (
            getattr(panel.parent, "callbacks", []), []
        )
        for callback in callbacks:
            callback()
        time.sleep(0.001)

    assert window.save_button.cget("state") == "normal"
    window._apply()
    drain_apply(window)
    assert len(apply_calls) == 1


def test_cancel_during_apply_signals_worker_and_closes_window(monkeypatch):
    started, release = Event(), Event()
    seen = []

    class Owner:
        def cancel_nano_settings(self):
            seen.append("cancel")

        def apply(self, *_args, **options):
            seen.append(options["cancel_event"])
            started.set()
            assert release.wait(2)
            return SettingsApplyResult(False)

    window = _window(monkeypatch, Owner().apply)
    try:
        window._apply()
        assert started.wait(1)
        window.close()
        assert seen[0].is_set()
        assert seen[1] == "cancel"
        assert not window.window.exists
    finally:
        release.set()
