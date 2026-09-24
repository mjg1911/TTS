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
        on_apply: Callable[[str, str, str, str, Optional[Path], str], SettingsApplyResult],
        on_close: Callable[[], None],
        on_speak_text: Callable[[str], None],
        on_verify_kokoro: Callable[[], bool],
    ) -> None:
        self.window = tk.Toplevel(parent)
        self.window.title("Piper Settings")
        if getattr(parent, "state", lambda: None)() != "withdrawn":
            self.window.transient(parent)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self._on_apply = on_apply
        self._on_close = on_close
        self._on_speak_text = on_speak_text
        self._on_verify_kokoro = on_verify_kokoro
        self._closed = False
        self.pending_voice_path: Optional[Path] = None
        self.displayed_voice_path = snapshot.piper_voice_path
        self.engine_var = tk.StringVar(value=snapshot.engine)
        self.kokoro_voice_var = tk.StringVar(value=snapshot.kokoro_voice)
        self.hotkey_var = tk.StringVar(value=snapshot.hotkey)
        self.pitch_var = tk.StringVar(value=f"{snapshot.pitch_percent:g}")
        self.speed_var = tk.StringVar(value=f"{snapshot.speed_percent:g}")
        self.engine_status_var = tk.StringVar(value="")
        self.kokoro_verify_status_var = tk.StringVar(value="")
        self._error_vars = {
            key: tk.StringVar(value="")
            for key in (
                "engine", "hotkey", "pitch", "speed", "piper_voice",
                "kokoro_voice", "voice", "general",
            )
        }
        self._build(snapshot)

    @property
    def destroyed(self) -> bool:
        return self._closed

    def _build(self, snapshot: SettingsWindowSnapshot) -> None:
        self.window.columnconfigure(0, weight=1)
        engine_frame = ttk.LabelFrame(self.window, text="Speech engine")
        engine_frame.grid(row=0, column=0, sticky="ew", padx=8, pady=4)
        combo = getattr(ttk, "Combobox", ttk.Entry)
        self.engine_combo = combo(
            engine_frame,
            textvariable=self.engine_var,
            values=("Piper", "Kokoro"),
            state="readonly",
        )
        self.engine_combo.grid(row=0, column=0, sticky="w", padx=6, pady=4)
        if hasattr(self.engine_combo, "bind"):
            self.engine_combo.bind(
                "<<ComboboxSelected>>", lambda _event: self._refresh_voice_controls()
            )
        ttk.Label(engine_frame, textvariable=self.engine_status_var).grid(
            row=0, column=1, sticky="w", padx=6, pady=4
        )
        ttk.Label(engine_frame, textvariable=self._error_vars["engine"]).grid(
            row=1, column=0, columnspan=2, sticky="w", padx=6
        )

        self.piper_voice_frame = ttk.LabelFrame(
            self.window, text="Piper voice model"
        )
        self.piper_voice_frame.grid(
            row=1, column=0, sticky="ew", padx=8, pady=4
        )
        self.piper_voice_frame.columnconfigure(0, weight=1)
        self.voice_label = ttk.Label(self.piper_voice_frame)
        self.voice_label.grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.voice_error_label = ttk.Label(
            self.piper_voice_frame, textvariable=self._error_vars["piper_voice"]
        )
        self.voice_error_label.grid(
            row=1, column=0, columnspan=2, sticky="w", padx=6, pady=(0, 4)
        )
        ttk.Button(
            self.piper_voice_frame, text="Choose voice...", command=self._choose_voice
        ).grid(row=0, column=1, padx=6, pady=4)
        self._set_voice_label(snapshot.piper_voice_path)

        self.kokoro_voice_frame = ttk.LabelFrame(self.window, text="Kokoro voice")
        self.kokoro_voice_frame.columnconfigure(0, weight=1)
        self.kokoro_voice_combo = combo(
            self.kokoro_voice_frame,
            textvariable=self.kokoro_voice_var,
            values=tuple(snapshot.kokoro_voices),
            state="readonly",
        )
        self.kokoro_voice_combo.grid(
            row=0, column=0, sticky="ew", padx=6, pady=4
        )
        ttk.Label(
            self.kokoro_voice_frame, textvariable=self._error_vars["kokoro_voice"]
        ).grid(row=1, column=0, sticky="w", padx=6, pady=(0, 4))
        if not snapshot.kokoro_available and snapshot.kokoro_unavailable_reason:
            self.engine_status_var.set(snapshot.kokoro_unavailable_reason)
            self.engine_var.set("Piper")
        self._refresh_voice_controls()

        maintenance_frame = ttk.LabelFrame(self.window, text="Kokoro maintenance")
        maintenance_frame.grid(row=2, column=0, sticky="ew", padx=8, pady=4)
        maintenance_frame.columnconfigure(0, weight=1)
        ttk.Label(
            maintenance_frame,
            text=(
                "Check the installed Kokoro model and runtime files for missing or "
                "corrupted data. This may take a few minutes."
            ),
            wraplength=420,
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=6, pady=(6, 2))
        self.kokoro_verify_button = ttk.Button(
            maintenance_frame,
            text="Verify Kokoro files",
            command=self._verify_kokoro,
        )
        self.kokoro_verify_button.grid(row=1, column=0, sticky="w", padx=6, pady=4)
        ttk.Label(
            maintenance_frame,
            textvariable=self.kokoro_verify_status_var,
        ).grid(row=1, column=1, sticky="w", padx=6, pady=4)

        text_frame = ttk.LabelFrame(self.window, text="Last captured text")
        text_frame.grid(row=3, column=0, sticky="nsew", padx=8, pady=4)
        self.last_text = tk.Text(text_frame, width=60, height=8, wrap="word")
        self.last_text.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self.speak_text_button = ttk.Button(
            text_frame, text="Speak text", command=self._speak_text
        )
        self.speak_text_button.grid(
            row=1, column=0, sticky="e", padx=6, pady=(0, 6)
        )
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)
        self.update_last_text(snapshot.last_text)
        self._build_percent_section(
            "Hotkey settings", 4, self.hotkey_var, self._error_vars["hotkey"], ""
        )
        self._build_percent_section(
            "Pitch settings", 5, self.pitch_var, self._error_vars["pitch"], "%"
        )
        self._build_percent_section(
            "Speed settings", 6, self.speed_var, self._error_vars["speed"], "%"
        )
        ttk.Label(self.window, textvariable=self._error_vars["general"]).grid(
            row=7, column=0, sticky="w", padx=8, pady=4
        )
        buttons = ttk.Frame(self.window)
        buttons.grid(row=8, column=0, sticky="e", padx=8, pady=8)
        ttk.Button(buttons, text="Save/Apply", command=self._apply).pack(
            side="left", padx=4
        )
        ttk.Button(buttons, text="Cancel", command=self.close).pack(
            side="left", padx=4
        )

    def _refresh_voice_controls(self) -> None:
        if self.engine_var.get() == "Kokoro":
            self._show_frame(self.piper_voice_frame, False)
            self._show_frame(self.kokoro_voice_frame, True)
        else:
            self._show_frame(self.piper_voice_frame, True)
            self._show_frame(self.kokoro_voice_frame, False)

    @staticmethod
    def _show_frame(frame, visible: bool) -> None:
        if visible:
            frame.grid(row=1, column=0, sticky="ew", padx=8, pady=4)
        elif hasattr(frame, "grid_remove"):
            frame.grid_remove()

    def _build_percent_section(self, title, row, variable, error_var, suffix):
        frame = ttk.LabelFrame(self.window, text=title)
        frame.grid(row=row, column=0, sticky="ew", padx=8, pady=4)
        frame.columnconfigure(0, weight=1)
        ttk.Entry(frame, textvariable=variable).grid(
            row=0, column=0, sticky="ew", padx=6, pady=4
        )
        if suffix:
            ttk.Label(frame, text=suffix).grid(
                row=0, column=1, padx=(0, 6), pady=4
            )
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
            self.engine_var.get(),
            self.hotkey_var.get(),
            self.pitch_var.get(),
            self.speed_var.get(),
            self.pending_voice_path,
            self.kokoro_voice_var.get(),
        )
        if not result.applied:
            for key, message in result.errors:
                target = "piper_voice" if key == "voice" else key
                if target in self._error_vars:
                    self._error_vars[target].set(message)
            return
        if result.snapshot is not None:
            self._refresh_from_snapshot(result.snapshot)
        self.close()

    def _refresh_from_snapshot(self, snapshot: SettingsWindowSnapshot) -> None:
        self.displayed_voice_path = snapshot.piper_voice_path
        self.pending_voice_path = None
        self.engine_var.set(snapshot.engine)
        self.kokoro_voice_var.set(snapshot.kokoro_voice)
        self.hotkey_var.set(snapshot.hotkey)
        self.pitch_var.set(f"{snapshot.pitch_percent:g}")
        self.speed_var.set(f"{snapshot.speed_percent:g}")
        self._set_voice_label(snapshot.piper_voice_path)
        self.update_last_text(snapshot.last_text)
        self._refresh_voice_controls()

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
        self.last_text.configure(state="normal")

    def _speak_text(self) -> None:
        text = self.last_text.get("1.0", "end-1c")
        if text.strip():
            self._on_speak_text(text)

    def _verify_kokoro(self) -> None:
        self.kokoro_verify_status_var.set("Verifying Kokoro files...")
        self.kokoro_verify_button.configure(state="disabled")
        if not self._on_verify_kokoro():
            self.kokoro_verify_status_var.set(
                "Kokoro verification is already running."
            )
            self.kokoro_verify_button.configure(state="normal")

    def update_kokoro_verification(self, message: str) -> None:
        self.kokoro_verify_status_var.set(message)
        self.kokoro_verify_button.configure(state="normal")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.window.destroy()
        finally:
            self._on_close()
