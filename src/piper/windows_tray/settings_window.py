from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk
from typing import Callable, Optional

from .controller import SettingsApplyResult, SettingsWindowSnapshot


def choose_voice_model(parent: tk.Misc) -> Optional[Path]:
    selected = filedialog.askopenfilename(
        parent=parent,
        title="Choose Piper voice model",
        filetypes=[("Piper ONNX model", "*.onnx")],
    )
    return Path(selected) if selected else None


class SettingsWindow:
    def __init__(
        self,
        parent: tk.Misc,
        snapshot: SettingsWindowSnapshot,
        on_apply: Callable[[str, str, str, Optional[Path]], SettingsApplyResult],
        on_close: Callable[[], None],
    ) -> None:
        self.window = tk.Toplevel(parent)
        self.window.title("Piper Settings")
        self.window.transient(parent)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        self._on_apply = on_apply
        self._on_close = on_close
        self._closed = False
        self.pending_voice_path: Optional[Path] = None
        self.displayed_voice_path = snapshot.voice_path

        self.hotkey_var = tk.StringVar(value=snapshot.hotkey)
        self.pitch_var = tk.StringVar(value=f"{snapshot.pitch_percent:g}")
        self.speed_var = tk.StringVar(value=f"{snapshot.speed_percent:g}")
        self._error_vars = {
            key: tk.StringVar(value="")
            for key in ("hotkey", "pitch", "speed", "voice", "general")
        }

        self._build(snapshot)

    @property
    def destroyed(self) -> bool:
        return self._closed

    def _build(self, snapshot: SettingsWindowSnapshot) -> None:
        self.window.columnconfigure(0, weight=1)

        voice_frame = ttk.LabelFrame(self.window, text="Voice model")
        voice_frame.grid(row=0, column=0, sticky="ew", padx=8, pady=4)
        voice_frame.columnconfigure(0, weight=1)
        self.voice_label = ttk.Label(voice_frame)
        self.voice_label.grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Button(
            voice_frame, text="Choose voice...", command=self._choose_voice
        ).grid(
            row=0, column=1, padx=6, pady=4
        )
        self._set_voice_label(snapshot.voice_path)

        text_frame = ttk.LabelFrame(self.window, text="Last captured text")
        text_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)
        self.last_text = tk.Text(text_frame, width=60, height=8, wrap="word")
        self.last_text.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)
        self.update_last_text(snapshot.last_text)

        self._build_percent_section(
            "Hotkey settings", 2, self.hotkey_var, self._error_vars["hotkey"], ""
        )
        self._build_percent_section(
            "Pitch settings", 3, self.pitch_var, self._error_vars["pitch"], "%"
        )
        self._build_percent_section(
            "Speed settings", 4, self.speed_var, self._error_vars["speed"], "%"
        )

        ttk.Label(self.window, textvariable=self._error_vars["general"]).grid(
            row=5, column=0, sticky="w", padx=8, pady=4
        )
        buttons = ttk.Frame(self.window)
        buttons.grid(row=6, column=0, sticky="e", padx=8, pady=8)
        ttk.Button(buttons, text="Save/Apply", command=self._apply).pack(
            side="left", padx=4
        )
        ttk.Button(buttons, text="Cancel", command=self.close).pack(side="left", padx=4)

    def _build_percent_section(self, title, row, variable, error_var, suffix):
        frame = ttk.LabelFrame(self.window, text=title)
        frame.grid(row=row, column=0, sticky="ew", padx=8, pady=4)
        frame.columnconfigure(0, weight=1)
        ttk.Entry(frame, textvariable=variable).grid(
            row=0, column=0, sticky="ew", padx=6, pady=4
        )
        if suffix:
            ttk.Label(frame, text=suffix).grid(row=0, column=1, padx=(0, 6), pady=4)
        ttk.Label(frame, textvariable=error_var).grid(
            row=0, column=2, sticky="w", padx=(0, 6), pady=4
        )

    def _set_voice_label(self, path: Optional[Path]) -> None:
        self.voice_label.configure(text=str(path) if path else "No voice loaded")

    def _choose_voice(self) -> None:
        selected = choose_voice_model(self.window)
        if selected is not None:
            self.pending_voice_path = selected
            self._set_voice_label(selected)

    def _clear_errors(self) -> None:
        for variable in self._error_vars.values():
            variable.set("")

    def error_text(self, key: str) -> str:
        return self._error_vars[key].get()

    def _apply(self) -> None:
        self._clear_errors()
        result = self._on_apply(
            self.hotkey_var.get(),
            self.pitch_var.get(),
            self.speed_var.get(),
            self.pending_voice_path,
        )
        if not result.applied:
            for key, message in result.errors:
                self._error_vars[key].set(message)
            return
        if result.snapshot is not None:
            self._refresh_from_snapshot(result.snapshot)
        self.close()

    def _refresh_from_snapshot(self, snapshot: SettingsWindowSnapshot) -> None:
        self.displayed_voice_path = snapshot.voice_path
        self.pending_voice_path = None
        self.hotkey_var.set(snapshot.hotkey)
        self.pitch_var.set(f"{snapshot.pitch_percent:g}")
        self.speed_var.set(f"{snapshot.speed_percent:g}")
        self._set_voice_label(snapshot.voice_path)
        self.update_last_text(snapshot.last_text)

    def focus(self) -> None:
        if self.window.winfo_exists():
            self.window.deiconify()
            self.window.lift()
            self.window.focus_force()

    def update_last_text(self, text: Optional[str]) -> None:
        value = text or "No text has been captured yet."
        self.last_text_value = text
        self.last_text.configure(state="normal")
        self.last_text.delete("1.0", "end")
        self.last_text.insert("1.0", value)
        self.last_text.configure(state="disabled")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.window.destroy()
        finally:
            self._on_close()
