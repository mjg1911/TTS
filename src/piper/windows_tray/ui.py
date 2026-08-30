from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from typing import Optional

from .settings import validate_pitch_percent


class TkUi:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.withdraw()
        self._thread_id = threading.get_ident()

    def _assert_main_thread(self) -> None:
        if threading.get_ident() != self._thread_id:
            raise RuntimeError("TkUi must be used from the Tk main thread")

    def choose_voice_model(self) -> Optional[Path]:
        self._assert_main_thread()
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Choose Piper voice model",
            filetypes=[("Piper ONNX model", "*.onnx")],
        )
        return Path(selected) if selected else None

    def show_status(self, message: str) -> None:
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
            messagebox.showerror(
                "Piper",
                "Pitch must be between -50% and 100%.",
                parent=self.root,
            )
            return None

    def close(self) -> None:
        self._assert_main_thread()
        self.root.destroy()
