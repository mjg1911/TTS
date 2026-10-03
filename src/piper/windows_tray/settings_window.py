from pathlib import Path
from queue import Queue, Empty
import threading
import tkinter as tk
from tkinter import filedialog, ttk
from typing import Callable, Optional

from .controller import SettingsApplyResult, SettingsWindowSnapshot
from .settings_theme import (
    ACCENT,
    BACKGROUND,
    BORDER,
    INPUT,
    TEXT,
    configure_studio_theme,
)


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
        on_apply: Callable[
            [
                str,
                str,
                str,
                str,
                Optional[Path],
                str,
                str,
                bool,
            ],
            SettingsApplyResult,
        ],
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
        self.chatterbox_device_var = tk.StringVar(value=snapshot.chatterbox_device)
        self.kokoro_voice_var = tk.StringVar(value=snapshot.kokoro_voice)
        self.hotkey_var = tk.StringVar(value=snapshot.hotkey)
        self.pitch_var = tk.StringVar(value=f"{snapshot.pitch_percent:g}")
        self.speed_var = tk.StringVar(value=f"{snapshot.speed_percent:g}")
        self.sentence_pause_var = tk.StringVar(value=str(snapshot.sentence_pause_ms))
        self.piper_sentence_streaming_var = tk.StringVar(
            value=("true" if snapshot.piper_sentence_streaming_enabled else "false")
        )
        self.engine_status_var = tk.StringVar(value=snapshot.chatterbox_device_message)
        self.kokoro_verify_status_var = tk.StringVar(value="")
        self._error_vars = {
            key: tk.StringVar(value="")
            for key in (
                "engine",
                "hotkey",
                "pitch",
                "speed",
                "sentence_pause",
                "piper_sentence_streaming",
                "piper_voice",
                "kokoro_voice",
                "voice",
                "general",
            )
        }
        self._build(snapshot)

    @property
    def destroyed(self) -> bool:
        return self._closed

    def _build(self, snapshot: SettingsWindowSnapshot) -> None:
        configure_studio_theme(self.window)
        self.window.geometry("1040x800")
        self.window.minsize(900, 680)
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(1, weight=1)
        self._error_labels = []

        header = ttk.Frame(self.window, style="Piper.TFrame", padding=(24, 18))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        mark = tk.Canvas(
            header, width=44, height=44, bg=BACKGROUND, highlightthickness=0
        )
        mark.grid(row=0, column=0, rowspan=2, padx=(0, 14))
        for x, height in ((8, 10), (15, 24), (22, 36), (29, 20), (36, 10)):
            mark.create_line(
                x,
                22 - height / 2,
                x,
                22 + height / 2,
                fill=ACCENT,
                width=3,
                capstyle="round",
            )
        ttk.Label(header, text="Piper", style="Title.Piper.TLabel").grid(
            row=0, column=1, sticky="w"
        )
        ttk.Label(
            header, text="Your text, given a voice.", style="Subtitle.Piper.TLabel"
        ).grid(row=1, column=1, sticky="w")
        ttk.Label(header, text="VOICE WORKSPACE", style="Badge.Piper.TLabel").grid(
            row=0, column=2, rowspan=2, sticky="e"
        )

        content = ttk.Frame(self.window, style="Piper.TFrame")
        content.grid(row=1, column=0, sticky="nsew", padx=24)
        content.columnconfigure(0, weight=0, minsize=360)
        content.columnconfigure(1, weight=1)
        content.rowconfigure(0, weight=1)
        sidebar = ttk.Frame(content, style="Piper.TFrame")
        sidebar.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
        sidebar.columnconfigure(0, weight=1)
        sidebar.rowconfigure(0, weight=1)
        self.settings_canvas = tk.Canvas(
            sidebar, width=360, bg=BACKGROUND, highlightthickness=0, bd=0
        )
        self.settings_canvas.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(
            sidebar,
            orient="vertical",
            command=self.settings_canvas.yview,
            style="Piper.Vertical.TScrollbar",
        )
        scroll.grid(row=0, column=1, sticky="ns", padx=(4, 0))
        self.settings_canvas.configure(yscrollcommand=scroll.set)
        self.controls = ttk.Frame(self.settings_canvas, style="Piper.TFrame")
        self.controls.columnconfigure(0, weight=1)
        self._controls_id = self.settings_canvas.create_window(
            0, 0, window=self.controls, anchor="nw"
        )
        self.controls.bind("<Configure>", self._update_scroll_region)
        self.settings_canvas.bind("<Configure>", self._resize_controls)

        voice = self._panel(self.controls, "Voice", 0)
        ttk.Label(voice, text="Speech engine", style="Muted.Piper.TLabel").grid(
            row=1, column=0, sticky="w", pady=(12, 5)
        )
        self.engine_combo = ttk.Combobox(
            voice,
            textvariable=self.engine_var,
            values=("Piper", "Kokoro", "Chatterbox Nano"),
            state="readonly",
            style="Piper.TCombobox",
            font=("Segoe UI", 10),
        )
        self.engine_combo.grid(row=2, column=0, sticky="ew")
        self.engine_combo.bind(
            "<<ComboboxSelected>>", lambda _: self._refresh_voice_controls()
        )
        self._error_label(voice, "engine", 3)
        self.nano_voice_frame = ttk.Frame(voice, style="Panel.Piper.TFrame")
        ttk.Label(
            self.nano_voice_frame,
            text="Default English voice",
            style="Muted.Piper.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(10, 5))
        device_controls = ttk.Frame(self.nano_voice_frame, style="Panel.Piper.TFrame")
        device_controls.grid(row=1, column=0, sticky="w", pady=(3, 5))
        ttk.Label(device_controls, text="Device", style="Muted.Piper.TLabel").grid(
            row=0, column=0, padx=(0, 12)
        )
        for column, (label, value) in enumerate((("CPU", "cpu"), ("GPU", "cuda")), 1):
            ttk.Radiobutton(
                device_controls,
                text=label,
                value=value,
                variable=self.chatterbox_device_var,
            ).grid(row=0, column=column, padx=(0, 10))
        ttk.Label(
            voice,
            textvariable=self.engine_status_var,
            style="Muted.Piper.TLabel",
            wraplength=310,
        ).grid(row=4, column=0, sticky="ew", pady=(6, 0))
        self.piper_voice_frame = ttk.Frame(voice, style="Panel.Piper.TFrame")
        self.piper_voice_frame.columnconfigure(0, weight=1)
        ttk.Label(
            self.piper_voice_frame, text="Piper voice model", style="Muted.Piper.TLabel"
        ).grid(row=0, column=0, sticky="w", pady=(10, 4))
        self.voice_name_label = ttk.Label(self.piper_voice_frame, style="Piper.TLabel")
        self.voice_name_label.grid(row=1, column=0, sticky="ew")
        self.voice_label = ttk.Label(
            self.piper_voice_frame,
            style="Muted.Piper.TLabel",
            wraplength=310,
            justify="left",
        )
        self.voice_label.grid(row=2, column=0, sticky="ew", pady=(3, 0))
        ttk.Button(
            self.piper_voice_frame,
            text="Choose voice…",
            command=self._choose_voice,
            style="Piper.TButton",
        ).grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.voice_error_label = self._error_label(
            self.piper_voice_frame, "piper_voice", 4
        )
        self._set_voice_label(snapshot.piper_voice_path)
        self.kokoro_voice_frame = ttk.Frame(voice, style="Panel.Piper.TFrame")
        self.kokoro_voice_frame.columnconfigure(0, weight=1)
        ttk.Label(
            self.kokoro_voice_frame, text="Kokoro voice", style="Muted.Piper.TLabel"
        ).grid(row=0, column=0, sticky="w", pady=(10, 5))
        self.kokoro_voice_combo = ttk.Combobox(
            self.kokoro_voice_frame,
            textvariable=self.kokoro_voice_var,
            values=tuple(snapshot.kokoro_voices),
            state="readonly",
            style="Piper.TCombobox",
            font=("Segoe UI", 10),
        )
        self.kokoro_voice_combo.grid(row=1, column=0, sticky="ew")
        self._error_label(self.kokoro_voice_frame, "kokoro_voice", 2)
        if (
            snapshot.engine == "Kokoro"
            and not snapshot.kokoro_available
            and snapshot.kokoro_unavailable_reason
        ):
            self.engine_status_var.set(snapshot.kokoro_unavailable_reason)
            self.engine_var.set("Piper")
        self._refresh_voice_controls()

        speech = self._panel(self.controls, "Speech tuning", 1)
        tuning = ttk.Frame(speech, style="Panel.Piper.TFrame")
        tuning.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        tuning.columnconfigure(0, weight=1)
        tuning.columnconfigure(1, weight=1)
        self._number_field(tuning, "Pitch", self.pitch_var, "pitch", "%", 0)
        self._number_field(tuning, "Speed", self.speed_var, "speed", "%", 1)
        ttk.Label(
            speech,
            text="0% keeps the voice’s natural pitch and speed.",
            style="Muted.Piper.TLabel",
            wraplength=310,
        ).grid(row=2, column=0, sticky="w", pady=(6, 10))
        self.pause_frame = ttk.Frame(speech, style="Panel.Piper.TFrame")
        self.pause_frame.columnconfigure(1, weight=1)
        ttk.Label(self.pause_frame, text="Piper pause", style="Piper.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 10)
        )
        ttk.Entry(
            self.pause_frame,
            textvariable=self.sentence_pause_var,
            width=7,
            style="Piper.TEntry",
            font=("Segoe UI", 10),
        ).grid(row=0, column=1, sticky="ew")
        ttk.Label(self.pause_frame, text="ms", style="Muted.Piper.TLabel").grid(
            row=0, column=2, padx=(6, 0)
        )
        self._error_label(self.pause_frame, "sentence_pause", 1, columnspan=3)
        self.piper_sentence_streaming_checkbutton = ttk.Checkbutton(
            self.pause_frame,
            text="Stream Piper sentences",
            variable=self.piper_sentence_streaming_var,
            onvalue="true",
            offvalue="false",
            style="Piper.TCheckbutton",
        )
        self.piper_sentence_streaming_checkbutton.grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(8, 0)
        )
        self._error_label(self.pause_frame, "piper_sentence_streaming", 3, columnspan=3)
        self.pause_frame.grid(row=3, column=0, sticky="ew")

        shortcut = self._panel(self.controls, "Capture shortcut", 2)
        ttk.Entry(
            shortcut,
            textvariable=self.hotkey_var,
            style="Piper.TEntry",
            font=("Segoe UI", 10),
        ).grid(row=1, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(
            shortcut,
            text="Read selected text with your shortcut. E.g. ctrl+shift+q",
            style="Muted.Piper.TLabel",
            wraplength=310,
        ).grid(row=2, column=0, sticky="w", pady=(6, 0))
        self._error_label(shortcut, "hotkey", 3)

        maintenance = self._panel(self.controls, "Kokoro maintenance", 3)
        ttk.Label(
            maintenance,
            text="Check installed model and runtime files. This may take a few minutes.",
            style="Muted.Piper.TLabel",
            wraplength=310,
        ).grid(row=1, column=0, sticky="w", pady=(8, 10))
        self.kokoro_verify_button = ttk.Button(
            maintenance,
            text="Verify Kokoro files",
            command=self._verify_kokoro,
            style="Piper.TButton",
        )
        self.kokoro_verify_button.grid(row=2, column=0, sticky="w")
        ttk.Label(
            maintenance,
            textvariable=self.kokoro_verify_status_var,
            style="Muted.Piper.TLabel",
            wraplength=310,
        ).grid(row=3, column=0, sticky="ew", pady=(6, 0))

        preview = ttk.Frame(content, style="Panel.Piper.TFrame", padding=20)
        preview.grid(row=0, column=1, sticky="nsew")
        preview.columnconfigure(0, weight=1)
        preview.rowconfigure(2, weight=1)
        ttk.Label(preview, text="Text to speech", style="Section.Piper.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            preview,
            text="Your latest capture appears here. Edit it, then listen.",
            style="Muted.Piper.TLabel",
            wraplength=390,
        ).grid(row=1, column=0, sticky="w", pady=(6, 18))
        editor = ttk.Frame(preview, style="Panel.Piper.TFrame")
        editor.grid(row=2, column=0, sticky="nsew")
        editor.columnconfigure(0, weight=1)
        editor.rowconfigure(0, weight=1)
        self.last_text = tk.Text(
            editor,
            width=30,
            height=12,
            wrap="word",
            font=("Segoe UI", 11),
            background=INPUT,
            foreground=TEXT,
            insertbackground=ACCENT,
            selectbackground="#315e57",
            selectforeground=TEXT,
            relief="flat",
            bd=0,
            padx=16,
            pady=14,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            undo=True,
        )
        self.last_text.grid(row=0, column=0, sticky="nsew")
        text_scroll = ttk.Scrollbar(
            editor,
            orient="vertical",
            command=self.last_text.yview,
            style="Piper.Vertical.TScrollbar",
        )
        text_scroll.grid(row=0, column=1, sticky="ns")
        self.last_text.configure(yscrollcommand=text_scroll.set)
        self.speak_text_button = ttk.Button(
            preview,
            text="▶  Speak text",
            command=self._speak_text,
            style="Primary.Piper.TButton",
        )
        self.speak_text_button.grid(row=3, column=0, sticky="ew", pady=(16, 0))
        self.update_last_text(snapshot.last_text)

        footer = ttk.Frame(self.window, style="Piper.TFrame", padding=(24, 16))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        general = ttk.Label(
            footer,
            textvariable=self._error_vars["general"],
            style="Error.Piper.TLabel",
            background=BACKGROUND,
            wraplength=430,
            justify="left",
        )
        general.grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.cancel_button = ttk.Button(
            footer, text="Cancel", command=self.close, style="Piper.TButton"
        )
        self.cancel_button.grid(row=0, column=1, padx=(0, 10))
        self.save_button = ttk.Button(
            footer,
            text="Save changes",
            command=self._apply,
            style="Primary.Piper.TButton",
        )
        self.save_button.grid(row=0, column=2)
        self._refresh_voice_controls()
        self._bind_settings_scroll(self.controls)
        self.settings_canvas.bind("<MouseWheel>", self._scroll_settings)
        self.window.bind("<Escape>", lambda _: self.close())

    def _panel(self, parent, title, row):
        frame = ttk.Frame(parent, style="Panel.Piper.TFrame", padding=16)
        frame.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text=title, style="Section.Piper.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        return frame

    def _error_label(self, parent, key, row, columnspan=1):
        label = ttk.Label(
            parent,
            textvariable=self._error_vars[key],
            style="Error.Piper.TLabel",
            wraplength=310,
            justify="left",
        )
        label.grid(row=row, column=0, columnspan=columnspan, sticky="ew", pady=(4, 0))
        label.grid_remove()
        self._error_labels.append((key, label))
        return label

    def _number_field(self, parent, title, variable, key, suffix, column):
        frame = ttk.Frame(parent, style="Panel.Piper.TFrame")
        frame.grid(
            row=0, column=column, sticky="nsew", padx=(0, 10) if column == 0 else 0
        )
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text=title, style="Muted.Piper.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 5)
        )
        ttk.Entry(
            frame,
            textvariable=variable,
            width=7,
            style="Piper.TEntry",
            font=("Segoe UI", 10),
        ).grid(row=1, column=0, sticky="ew")
        ttk.Label(frame, text=suffix, style="Muted.Piper.TLabel").grid(
            row=1, column=1, padx=(6, 0)
        )
        label = self._error_label(frame, key, 2, columnspan=2)
        label.configure(wraplength=130)

    def _refresh_voice_controls(self) -> None:
        kokoro = self.engine_var.get() == "Kokoro"
        self._show_frame(self.piper_voice_frame, self.engine_var.get() == "Piper")
        self._show_frame(
            self.nano_voice_frame, self.engine_var.get() == "Chatterbox Nano"
        )
        self._show_frame(self.kokoro_voice_frame, kokoro)

    @staticmethod
    def _show_frame(frame, visible: bool) -> None:
        if visible:
            frame.grid(row=5, column=0, sticky="ew")
        else:
            frame.grid_remove()

    def _update_scroll_region(self, _event=None):
        self.settings_canvas.configure(scrollregion=self.settings_canvas.bbox("all"))

    def _resize_controls(self, event):
        self.settings_canvas.itemconfigure(self._controls_id, width=event.width)

    def _scroll_settings(self, event):
        if self.controls.winfo_height() > self.settings_canvas.winfo_height():
            self.settings_canvas.yview_scroll(-int(event.delta / 120), "units")
        return "break"

    def _bind_settings_scroll(self, widget):
        # Bind only the settings column; the text editor keeps its own scrolling.
        if widget.winfo_class() != "TCombobox":
            widget.bind("<MouseWheel>", self._scroll_settings)
        widget.bind(
            "<FocusIn>", lambda event: self._reveal_setting(event.widget), add="+"
        )
        for child in widget.winfo_children():
            self._bind_settings_scroll(child)

    def _reveal_setting(self, widget):
        canvas = self.settings_canvas
        height = self.controls.winfo_height()
        if height <= canvas.winfo_height():
            return
        top = widget.winfo_rooty() - self.controls.winfo_rooty()
        bottom = top + widget.winfo_height()
        visible_top = canvas.canvasy(0)
        if top < visible_top:
            canvas.yview_moveto(max(0, top - 12) / height)
        elif bottom > visible_top + canvas.winfo_height():
            canvas.yview_moveto((bottom + 12 - canvas.winfo_height()) / height)

    def _render_errors(self):
        for key, label in self._error_labels:
            if self._error_vars[key].get():
                label.grid()
            else:
                label.grid_remove()

    def _set_voice_label(self, path: Optional[Path]) -> None:
        self.voice_name_label.configure(
            text=path.name if path else "Choose a voice to get started", wraplength=310
        )
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
        self._render_errors()
        if getattr(self, "_apply_in_progress", False):
            return
        arguments = (
            self.engine_var.get(),
            self.hotkey_var.get(),
            self.pitch_var.get(),
            self.speed_var.get(),
            self.pending_voice_path if self.engine_var.get() == "Piper" else None,
            self.kokoro_voice_var.get(),
            self.sentence_pause_var.get(),
            self.piper_sentence_streaming_var.get() == "true",
        )
        if arguments[0] != "Chatterbox Nano":
            self._finish_apply(self._on_apply(*arguments))
            return
        self._apply_in_progress = True
        self._apply_cancel_event = threading.Event()
        self.engine_status_var.set("Preparing Chatterbox Nano...")
        device = self.chatterbox_device_var.get()
        results = Queue(maxsize=1)

        def apply_background():
            try:
                owner = getattr(self._on_apply, "__self__", None)
                if hasattr(owner, "cancel_nano_settings"):
                    result = self._on_apply(
                        *arguments,
                        cancel_event=self._apply_cancel_event,
                        chatterbox_device=device,
                    )
                else:
                    result = self._on_apply(*arguments)
            except Exception:
                result = SettingsApplyResult(
                    False, (("engine", "Chatterbox Nano is not available."),)
                )
            results.put(result)

        def poll():
            if self._closed:
                return
            try:
                result = results.get_nowait()
            except Empty:
                self.window.after(25, poll)
                return
            self._apply_in_progress = False
            self.engine_status_var.set("")
            self._finish_apply(result)

        threading.Thread(
            target=apply_background, name="nano-settings", daemon=True
        ).start()
        self.window.after(25, poll)

    def _finish_apply(self, result):
        if not result.applied:
            for key, message in result.errors:
                target = "piper_voice" if key == "voice" else key
                if target in self._error_vars:
                    self._error_vars[target].set(message)
            self._render_errors()
            self.window.update_idletasks()
            for key, label in self._error_labels:
                if self._error_vars[key].get():
                    self._reveal_setting(label)
                    break
            return
        if result.snapshot is not None:
            self._refresh_from_snapshot(result.snapshot)
            if result.snapshot.chatterbox_device_message:
                self.engine_status_var.set(result.snapshot.chatterbox_device_message)
                return
        self.close()

    def _refresh_from_snapshot(self, snapshot: SettingsWindowSnapshot) -> None:
        self.displayed_voice_path = snapshot.piper_voice_path
        self.pending_voice_path = None
        self.engine_var.set(snapshot.engine)
        self.chatterbox_device_var.set(snapshot.chatterbox_device)
        self.engine_status_var.set(snapshot.chatterbox_device_message)
        self.kokoro_voice_var.set(snapshot.kokoro_voice)
        self.hotkey_var.set(snapshot.hotkey)
        self.pitch_var.set(f"{snapshot.pitch_percent:g}")
        self.speed_var.set(f"{snapshot.speed_percent:g}")
        self.sentence_pause_var.set(str(snapshot.sentence_pause_ms))
        self.piper_sentence_streaming_var.set(
            "true" if snapshot.piper_sentence_streaming_enabled else "false"
        )
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
            self.kokoro_verify_status_var.set("Kokoro verification is already running.")
            self.kokoro_verify_button.configure(state="normal")

    def update_kokoro_verification(self, message: str) -> None:
        self.kokoro_verify_status_var.set(message)
        self.kokoro_verify_button.configure(state="normal")

    def close(self) -> None:
        if self._closed:
            return
        if getattr(self, "_apply_in_progress", False):
            self._apply_cancel_event.set()
        self._closed = True
        try:
            self.window.destroy()
        finally:
            self._on_close()
