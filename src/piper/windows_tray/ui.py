from pathlib import Path
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import Optional

from piper.turbo_options import ENGINE as TURBO_ENGINE

from .settings import validate_pitch_percent, validate_speed_percent
from .settings_window import SettingsWindow, choose_voice_model
from .controller import SettingsWindowSnapshot


class TkUi:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.withdraw()
        self._thread_id = threading.get_ident()
        self._settings_window: Optional[SettingsWindow] = None
        self._status_window: Optional[tk.Toplevel] = None
        self._status_message = tk.StringVar(master=self.root)

    def _assert_main_thread(self) -> None:
        if threading.get_ident() != self._thread_id:
            raise RuntimeError("TkUi must be used from the Tk main thread")

    def choose_voice_model(self) -> Optional[Path]:
        self._assert_main_thread()
        return choose_voice_model(self.root)

    def choose_startup_engine(self, current: str) -> Optional[str]:
        """Wait for an explicit model choice before startup loads any model."""
        self._assert_main_thread()
        selected = None
        window = tk.Toplevel(self.root)
        window.title("Piper — Choose a model")
        window.resizable(False, False)

        def choose(engine: Optional[str]) -> None:
            nonlocal selected
            selected = engine
            window.destroy()

        window.protocol("WM_DELETE_WINDOW", lambda: choose(None))
        window.bind("<Escape>", lambda _event: choose(None))
        body = ttk.Frame(window, padding=24)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Choose a speech model", font=("Segoe UI", 14, "bold")).pack(
            fill="x", pady=(0, 8)
        )
        ttk.Label(
            body,
            text="Select a model to start. No models load until you choose.",
            wraplength=360,
        ).pack(fill="x", pady=(0, 20))
        preferred = None
        for label, engine in (
            ("Piper", "Piper"),
            ("Chatterbox Nano", "Chatterbox Nano"),
            ("Chatterbox Turbo", TURBO_ENGINE),
        ):
            button = ttk.Button(
                body, text=label, command=lambda engine=engine: choose(engine)
            )
            button.pack(fill="x", pady=4, ipady=6)
            if engine == current:
                preferred = button
        # A transient of the withdrawn root would also be hidden on Windows.
        window.wait_visibility()
        window.grab_set()
        window.lift()
        window.focus_force()
        if preferred is not None:
            preferred.focus_set()
        self.root.wait_window(window)
        return selected

    def open_settings(
        self,
        snapshot: SettingsWindowSnapshot,
        on_apply,
        on_speak_text,
    ) -> None:
        self._assert_main_thread()
        current = self._settings_window
        if current is not None:
            current.focus()
            return

        def cleared() -> None:
            self._settings_window = None

        self._settings_window = SettingsWindow(
            parent=self.root,
            snapshot=snapshot,
            on_apply=on_apply,
            on_speak_text=on_speak_text,
            on_close=cleared,
        )
        self._settings_window.focus()

    def update_settings_last_text(self, text: Optional[str]) -> None:
        self._assert_main_thread()
        if self._settings_window is not None:
            self._settings_window.update_last_text(text)

    def show_status(self, message: str) -> None:
        """Show a runtime message without pausing the command pump."""
        self._assert_main_thread()
        self._status_message.set(message)
        if self._status_window is not None:
            self._status_window.deiconify()
            return

        window = tk.Toplevel(self.root)
        self._status_window = window
        window.title("Piper")
        # The root is withdrawn: making this window transient would hide it too.
        window.resizable(False, False)
        window.protocol("WM_DELETE_WINDOW", self._close_status)
        window.bind("<Escape>", lambda _event: self._close_status())
        body = ttk.Frame(window, padding=20)
        body.pack(fill="both", expand=True)
        ttk.Label(
            body,
            textvariable=self._status_message,
            wraplength=420,
            justify="left",
        ).pack(fill="x", pady=(0, 16))
        ttk.Button(body, text="Dismiss", command=self._close_status).pack(anchor="e")

    def _close_status(self) -> None:
        self._assert_main_thread()
        if self._status_window is not None:
            self._status_window.destroy()
            self._status_window = None

    def show_startup_status(self, message: str) -> None:
        """Keep fatal startup messages visible until acknowledged before exit."""
        self._assert_main_thread()
        messagebox.showinfo("Piper", message, parent=self.root)

    def show_last_text(self, text: Optional[str]) -> None:
        self._assert_main_thread()
        messagebox.showinfo(
            "Last captured text",
            text or "No text has been captured yet.",
            parent=self.root,
        )

    def prompt_hotkey(self, current: str) -> Optional[str]:
        self._assert_main_thread()
        value = simpledialog.askstring(
            "Capture hotkey",
            "Enter a hotkey such as Alt+backtick or Ctrl+Shift+Q",
            initialvalue=current,
            parent=self.root,
        )
        return value.strip() if value and value.strip() else None

    def prompt_pitch(self, current: float) -> Optional[float]:
        self._assert_main_thread()
        initial = f"{current:g}"
        value = simpledialog.askstring(
            "Pitch settings",
            "Enter pitch from -50% to 100%. Speech speed is preserved.",
            initialvalue=initial,
            parent=self.root,
        )
        if value is None:
            return None
        try:
            return validate_pitch_percent(float(value.strip()))
        except (ValueError, OverflowError):
            self.show_status("Pitch must be between -50% and 100%.")
            return None

    def prompt_speed(self, current: float) -> Optional[float]:
        self._assert_main_thread()
        value = simpledialog.askstring(
            "Speed settings",
            "Enter speed from -50% to 100%. Speed does not change pitch.",
            initialvalue=f"{current:g}",
            parent=self.root,
        )
        if value is None:
            return None
        try:
            return validate_speed_percent(float(value.strip()))
        except (ValueError, OverflowError):
            self.show_status("Speed must be between -50% and 100%.")
            return None

    def close(self) -> None:
        self._assert_main_thread()
        self._close_status()
        if self._settings_window is not None:
            self._settings_window.close()
            self._settings_window = None
        self.root.destroy()
