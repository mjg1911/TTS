import threading
import tkinter as tk

import pytest

from piper.windows_tray.ui import TkUi


@pytest.fixture(scope="module")
def tk_ui():
    try:
        instance = TkUi()
    except tk.TclError as error:
        pytest.skip(f"A working Tk display is required: {error}")
    try:
        yield instance
    finally:
        instance.close()


@pytest.fixture
def ui(tk_ui, monkeypatch):
    # A regression must fail immediately rather than opening a blocking dialog.
    def modal_dialog(*_args, **_kwargs):
        pytest.fail("Runtime errors must not use a modal message box")

    monkeypatch.setattr("piper.windows_tray.ui.messagebox.showinfo", modal_dialog)
    try:
        yield tk_ui
    finally:
        tk_ui._close_status()
        tk_ui.root.update()


def test_error_window_leaves_command_processing_running(ui):
    processed = []

    def pump():
        ui.show_status("Audio playback failed.")
        ui.root.after(0, lambda: processed.append("next command"))

    ui.root.after(0, pump)
    ui.root.update()

    assert processed == ["next command"]
    assert ui._status_window.winfo_viewable()
    assert ui.root.grab_current() is None


def test_repeated_errors_update_one_window(ui):
    ui.show_status("First error")
    window = ui._status_window
    ui.show_status("First error")
    ui.show_status("Second error")

    assert ui._status_window is window
    assert ui._status_message.get() == "Second error"
    assert ui.root.winfo_children() == [window]


def test_dismissed_error_can_be_shown_again(ui):
    ui.show_status("First error")
    window = ui._status_window
    ui._close_status()

    assert not window.winfo_exists()
    assert ui._status_window is None

    ui.show_status("Second error")
    assert ui._status_window is not window
    assert ui._status_message.get() == "Second error"


def test_status_requires_tk_thread(ui):
    errors = []

    def from_worker():
        try:
            ui.show_status("Error")
        except RuntimeError as error:
            errors.append(str(error))

    worker = threading.Thread(target=from_worker)
    worker.start()
    worker.join(timeout=2)

    assert errors == ["TkUi must be used from the Tk main thread"]


def test_dismiss_button_closes_window(ui):
    ui.show_status("Error")
    window = ui._status_window
    body = window.winfo_children()[0]
    button = body.winfo_children()[-1]

    assert button.cget("text") == "Dismiss"
    button.invoke()

    assert ui._status_window is None
    assert not window.winfo_exists()


def test_window_close_button_clears_status(ui):
    ui.show_status("Error")
    window = ui._status_window
    window.tk.call(window.protocol("WM_DELETE_WINDOW"))

    assert ui._status_window is None
    assert not window.winfo_exists()


def test_fatal_startup_status_waits_for_acknowledgement(ui, monkeypatch):
    messages = []
    monkeypatch.setattr(
        "piper.windows_tray.ui.messagebox.showinfo",
        lambda title, message, **kwargs: messages.append((title, message, kwargs)),
    )

    ui.show_startup_status("Voice could not be loaded.")

    assert messages == [("Piper", "Voice could not be loaded.", {"parent": ui.root})]
    assert ui._status_window is None
