"""Behavioral tests for the on-demand model download panel."""

import threading
import time
from types import SimpleNamespace

import pytest

from tests.windows_tray.test_settings_window import FakeVar, FakeWidget


class FakeParent(FakeWidget):
    def __init__(self):
        super().__init__()
        self.callbacks = []

    def after(self, _delay, callback):
        self.callbacks.append(callback)

    def pump_until(self, predicate, timeout=2):
        deadline = time.monotonic() + timeout
        while not predicate():
            assert time.monotonic() < deadline, "model download UI did not update"
            callbacks, self.callbacks = self.callbacks, []
            for callback in callbacks:
                callback()
            time.sleep(0.001)


class FakeButton(FakeWidget):
    def invoke(self):
        if self.cget("state") != "disabled":
            self.kwargs["command"]()


def install_fake_tk(monkeypatch):
    import piper.windows_tray.model_download_ui as module

    fake_ttk = SimpleNamespace(
        Frame=FakeWidget,
        Label=FakeWidget,
        Button=FakeButton,
        Progressbar=FakeWidget,
    )
    fake_tk = SimpleNamespace(StringVar=FakeVar)
    monkeypatch.setattr(module, "ttk", fake_ttk)
    monkeypatch.setattr(module, "tk", fake_tk)
    return module


def wait_state(parent, panel, state):
    parent.pump_until(lambda: panel.state == state)


def test_piper_is_always_available_without_local_probe_or_download(monkeypatch):
    module = install_fake_tk(monkeypatch)
    calls = []
    panel = module.ModelDownloadPanel(
        FakeParent(),
        engine_installed_fn=lambda engine: calls.append(("check", engine)),
        download_engine_fn=lambda *args: calls.append(("download", args[0])),
    )

    panel.set_engine("Piper")

    assert panel.is_ready
    assert panel.state == "available"
    assert panel.status_label.hidden is True
    assert calls == []


@pytest.mark.parametrize("engine", ["Chatterbox Nano", "Chatterbox Turbo (350M)"])
def test_missing_engine_is_checked_offline_and_exposes_download_button(
    monkeypatch, engine
):
    module = install_fake_tk(monkeypatch)
    parent = FakeParent()
    calls = []
    ui_thread = threading.get_ident()

    def missing(selected):
        calls.append((selected, threading.get_ident()))
        return False

    panel = module.ModelDownloadPanel(
        parent,
        engine_installed_fn=missing,
        download_engine_fn=lambda *args: calls.append(("download", args[0])),
    )
    panel.set_engine(engine)
    wait_state(parent, panel, "missing")

    assert panel.is_ready is False
    assert calls == [(engine, calls[0][1])]
    assert calls[0][1] != ui_thread
    assert panel.status_label.hidden is False
    assert panel.download_button.hidden is False
    assert panel.download_button.cget("text") == f"Download {engine}"


@pytest.mark.parametrize("engine", ["Chatterbox Nano", "Chatterbox Turbo (350M)"])
def test_installed_engine_is_ready_without_showing_download(monkeypatch, engine):
    module = install_fake_tk(monkeypatch)
    parent = FakeParent()
    panel = module.ModelDownloadPanel(
        parent,
        engine_installed_fn=lambda selected: selected == engine,
        download_engine_fn=lambda *_args: pytest.fail("installed model downloaded"),
    )

    panel.set_engine(engine)
    wait_state(parent, panel, "ready")

    assert panel.is_ready
    assert panel.download_button.hidden is True
    assert engine in panel.status_var.get()


def test_download_progress_failure_retry_and_installing_phase(monkeypatch):
    module = install_fake_tk(monkeypatch)
    parent = FakeParent()
    attempts = []
    release_first = threading.Event()
    installing_phase_seen = threading.Event()

    def download(engine, progress, cancel_event):
        attempts.append(engine)
        if len(attempts) == 1:
            progress(400, 1000, "worker")
            assert release_first.wait(2)
            raise RuntimeError("network unavailable")
        progress(1000, 1000, "nano")
        assert cancel_event.is_set() is False
        # Hold after reporting complete bytes so Tk can display verification.
        time.sleep(0.03)
        return "generation"

    panel = module.ModelDownloadPanel(
        parent,
        engine_installed_fn=lambda _engine: False,
        download_engine_fn=download,
    )
    panel.set_engine("Chatterbox Nano")
    wait_state(parent, panel, "missing")
    panel.download_button.invoke()
    parent.pump_until(lambda: panel.progress_bar.cget("value") == 40)
    assert panel.state == "downloading"
    assert "40%" in panel.status_var.get()
    release_first.set()
    wait_state(parent, panel, "error")
    assert "network unavailable" in panel.status_var.get()
    assert panel.download_button.cget("text") == "Retry download"

    panel.download_button.invoke()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        callbacks, parent.callbacks = parent.callbacks, []
        for callback in callbacks:
            callback()
        if panel.state == "installing":
            installing_phase_seen.set()
        if panel.state == "ready":
            break
        time.sleep(0.001)

    assert installing_phase_seen.is_set()
    assert panel.state == "ready"
    assert attempts == ["Chatterbox Nano", "Chatterbox Nano"]


def test_switching_engines_ignores_late_readiness_result(monkeypatch):
    module = install_fake_tk(monkeypatch)
    parent = FakeParent()
    release_nano = threading.Event()
    reports = []

    def readiness(engine):
        if engine == "Chatterbox Nano":
            assert release_nano.wait(2)
            return True
        return False

    panel = module.ModelDownloadPanel(
        parent,
        engine_installed_fn=readiness,
        download_engine_fn=lambda *_args: None,
        on_state_change=lambda engine, state, ready: reports.append(
            (engine, state, ready)
        ),
    )
    panel.set_engine("Chatterbox Nano")
    panel.set_engine("Chatterbox Turbo (350M)")
    wait_state(parent, panel, "missing")
    release_nano.set()
    parent.pump_until(lambda: not any(thread.is_alive() for thread in panel._threads))

    assert panel.selected_engine == "Chatterbox Turbo (350M)"
    assert panel.state == "missing"
    assert all(engine != "Chatterbox Nano" or state == "checking"
               for engine, state, _ready in reports)


def test_switching_engines_ignores_late_download_progress(monkeypatch):
    module = install_fake_tk(monkeypatch)
    parent = FakeParent()
    download_started = threading.Event()
    release_download = threading.Event()
    progress_statuses = []

    def download(_engine, progress, _cancel_event):
        download_started.set()
        assert release_download.wait(2)
        progress(60, 100, "nano")
        return "stale-generation"

    panel = module.ModelDownloadPanel(
        parent,
        engine_installed_fn=lambda _engine: False,
        download_engine_fn=download,
        on_state_change=lambda _engine, _state, _ready: progress_statuses.append(
            panel.status_var.get()
        ),
    )
    panel.set_engine("Chatterbox Nano")
    wait_state(parent, panel, "missing")
    panel.download_button.invoke()
    assert download_started.wait(1)
    panel.set_engine("Chatterbox Turbo (350M)")
    wait_state(parent, panel, "missing")
    release_download.set()
    parent.pump_until(
        lambda: not any(thread.is_alive() for thread in panel._threads)
        and panel._events.empty()
    )

    assert panel.selected_engine == "Chatterbox Turbo (350M)"
    assert panel.state == "missing"
    assert panel.progress_bar.cget("value") == 0
    assert not any("60%" in status for status in progress_statuses)


def test_close_cancels_active_download_and_ignores_queued_progress(monkeypatch):
    module = install_fake_tk(monkeypatch)
    parent = FakeParent()
    started = threading.Event()
    cancellation_seen = threading.Event()

    def download(_engine, progress, cancel_event):
        started.set()
        while not cancel_event.wait(0.005):
            progress(1, 10, "worker")
        cancellation_seen.set()
        return "cancelled"

    panel = module.ModelDownloadPanel(
        parent,
        engine_installed_fn=lambda _engine: False,
        download_engine_fn=download,
    )
    panel.set_engine("Chatterbox Nano")
    wait_state(parent, panel, "missing")
    panel.start_download()
    assert started.wait(1)

    panel.close()
    assert cancellation_seen.wait(1)
    assert panel.state == "closed"


def test_real_tk_panel_respects_pack_and_grid_owned_by_callers():
    import tkinter as tk

    from piper.windows_tray.model_download_ui import ModelDownloadPanel

    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError as error:
        pytest.skip(f"Tk display is unavailable: {error}")

    panels = []
    try:
        for manager in ("pack", "grid"):
            parent = tk.Frame(root)
            parent.pack()
            panel = ModelDownloadPanel(
                parent, engine_installed_fn=lambda _engine: True
            )
            panels.append(panel)
            getattr(panel.frame, manager)(fill="x") if manager == "pack" else (
                panel.frame.grid(sticky="ew")
            )
            panel.set_engine("Chatterbox Nano")
            deadline = time.monotonic() + 2
            while panel.state != "ready" and time.monotonic() < deadline:
                root.update()
                time.sleep(0.001)
            assert panel.state == "ready"
    finally:
        for panel in panels:
            panel.close()
        root.destroy()
