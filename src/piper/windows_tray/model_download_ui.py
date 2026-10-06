"""Threaded Tk panel for checking and downloading optional speech engines."""

from __future__ import annotations

from queue import Empty, Queue
import threading
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from .model_download import download_engine, engine_installed
from piper.turbo_options import ENGINE as TURBO_ENGINE


PIPER_ENGINE = "Piper"
NANO_ENGINE = "Chatterbox Nano"
CHATTERBOX_ENGINES = (NANO_ENGINE, TURBO_ENGINE)


class ModelDownloadPanel:
    """Display local readiness and explicitly requested downloads for one engine.

    All readiness checks and downloads run on worker threads. Worker events are
    tagged with the selected-engine generation and are rendered by ``after`` on
    the Tk thread. The constructor is deliberately usable by both Settings and
    the startup chooser; callers select an engine with :meth:`set_engine`.
    """

    def __init__(
        self,
        parent: tk.Misc,
        on_state_change: Optional[Callable[[str, str, bool], None]] = None,
        *,
        engine_installed_fn: Optional[Callable[[str], bool]] = None,
        download_engine_fn: Optional[Callable] = None,
        poll_interval_ms: int = 50,
    ) -> None:
        self.parent = parent
        self._on_state_change = on_state_change
        self._engine_installed = engine_installed_fn or engine_installed
        self._download_engine = download_engine_fn or download_engine
        self._poll_interval_ms = poll_interval_ms
        self._events: Queue[tuple] = Queue()
        self._threads: list[threading.Thread] = []
        self._generation = 0
        self._cancel_event: Optional[threading.Event] = None
        self._closed = False
        self._poll_id = None
        self.selected_engine: Optional[str] = None
        self.state = "available"
        self.frame = ttk.Frame(parent)
        self.status_var = tk.StringVar(value="")
        self.status_label = ttk.Label(self.frame, textvariable=self.status_var)
        self.status_label.grid(row=0, column=0, sticky="ew")
        self.status_label.grid_remove()
        self.progress_bar = ttk.Progressbar(
            self.frame, mode="determinate", maximum=100, value=0
        )
        self.progress_bar.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.download_button = ttk.Button(
            self.frame, text="Download", command=self.start_download
        )
        self.download_button.grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.frame.columnconfigure(0, weight=1)
        self.progress_bar.grid_remove()
        self.download_button.grid_remove()

    @property
    def is_ready(self) -> bool:
        return self.state == "available" if self.selected_engine == PIPER_ENGINE else (
            self.state == "ready"
        )

    def set_engine(self, engine: str) -> None:
        """Select an engine and begin a background-only local readiness check."""
        if engine != PIPER_ENGINE and engine not in CHATTERBOX_ENGINES:
            raise ValueError("engine must be Piper, Chatterbox Nano, or Chatterbox Turbo")
        if self._closed or engine == self.selected_engine:
            return

        self._generation += 1
        generation = self._generation
        if self._cancel_event is not None:
            self._cancel_event.set()
            self._cancel_event = None
        self.selected_engine = engine

        if engine == PIPER_ENGINE:
            self._set_state("available", "Piper is ready to use.")
            return

        self._set_state("checking", f"Checking whether {engine} is installed…")

        def check_in_background() -> None:
            try:
                ready = bool(self._engine_installed(engine))
            except Exception as error:
                self._events.put((generation, "check_error", str(error)))
            else:
                self._events.put((generation, "checked", ready))

        self._start_worker(check_in_background, "model-readiness")

    def start_download(self) -> None:
        """Start or retry a download after an explicit button click."""
        engine = self.selected_engine
        if self._closed or engine not in CHATTERBOX_ENGINES:
            return
        if self.state not in ("missing", "error"):
            return

        generation = self._generation
        cancel_event = threading.Event()
        self._cancel_event = cancel_event
        self._set_state("downloading", f"Downloading {engine}…")
        self.progress_bar.configure(value=0)

        def progress(completed: int, total: int, _component: str) -> None:
            self._events.put((generation, "progress", (completed, total)))
            if total > 0 and completed >= total:
                # Pause at the phase boundary so Tk can show verification and
                # installation before extraction and activation continue.
                acknowledged = threading.Event()
                self._events.put((generation, "installing", acknowledged))
                while not acknowledged.wait(0.05):
                    if cancel_event.is_set():
                        break

        def download_in_background() -> None:
            try:
                self._download_engine(engine, progress, cancel_event)
            except Exception as error:
                self._events.put((generation, "download_error", str(error)))
            else:
                self._events.put((generation, "downloaded", None))

        self._start_worker(download_in_background, "model-download")

    def close(self) -> None:
        """Cancel a running download and prevent later worker events from rendering."""
        if self._closed:
            return
        self._closed = True
        self._generation += 1
        if self._poll_id is not None:
            cancel_after = getattr(self.parent, "after_cancel", None)
            if cancel_after is not None:
                try:
                    cancel_after(self._poll_id)
                except Exception:
                    pass
            self._poll_id = None
        if self._cancel_event is not None:
            self._cancel_event.set()
            self._cancel_event = None
        self.state = "closed"

    def _set_state(self, state: str, message: str) -> None:
        self.state = state
        if self.selected_engine == PIPER_ENGINE:
            self.status_var.set("")
            self.status_label.grid_remove()
        else:
            self.status_var.set(message)
            self.status_label.grid(row=0, column=0, sticky="ew")
        checking = state in ("checking", "downloading", "installing")
        self.progress_bar.grid() if checking else self.progress_bar.grid_remove()
        has_download = state in ("missing", "error")
        if has_download:
            self.download_button.configure(
                text=("Retry download" if state == "error" else
                      f"Download {self.selected_engine}")
            )
            self.download_button.grid()
        else:
            self.download_button.grid_remove()
        if self._on_state_change is not None and not self._closed:
            self._on_state_change(self.selected_engine, state, self.is_ready)

    def _start_worker(self, target: Callable[[], None], name: str) -> None:
        thread = threading.Thread(target=target, name=name, daemon=True)
        self._threads.append(thread)
        thread.start()
        self._schedule_poll()

    def _schedule_poll(self) -> None:
        if not self._closed and self._poll_id is None:
            self._poll_id = self.parent.after(self._poll_interval_ms, self._poll)

    def _poll(self) -> None:
        """Drain worker events on Tk's main thread and discard stale generations."""
        self._poll_id = None
        while True:
            try:
                generation, event, value = self._events.get_nowait()
            except Empty:
                break
            if event == "installing" and (
                self._closed or generation != self._generation
            ):
                value.set()
                continue
            if self._closed or generation != self._generation:
                continue
            if event == "checked":
                if value:
                    self._set_state("ready", f"{self.selected_engine} is ready to use.")
                else:
                    self._set_state(
                        "missing", f"{self.selected_engine} is not installed."
                    )
            elif event == "check_error":
                self._set_state(
                    "error", f"Could not check {self.selected_engine}: {value}"
                )
            elif event == "progress":
                completed, total = value
                percent = min(100, max(0, int(completed * 100 / total))) if total else 0
                self.progress_bar.configure(value=percent)
                self.status_var.set(
                    f"Downloading {self.selected_engine}… {percent}%"
                )
            elif event == "installing":
                self.progress_bar.configure(value=100)
                self._set_state(
                    "installing", "Verifying and installing model files…"
                )
                value.set()
                break
            elif event == "downloaded":
                self._cancel_event = None
                self._set_state(
                    "ready", f"{self.selected_engine} is ready to use."
                )
            elif event == "download_error":
                self._cancel_event = None
                self._set_state(
                    "error", f"Could not download {self.selected_engine}: {value}"
                )

        self._threads = [thread for thread in self._threads if thread.is_alive()]
        if self._threads or not self._events.empty():
            self._schedule_poll()
