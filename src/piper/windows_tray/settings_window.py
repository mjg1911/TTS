from pathlib import Path
from queue import Queue, Empty
import threading
import tkinter as tk
from tkinter import filedialog, ttk
from typing import Callable, Optional

from piper.multilingual_options import ENGINE as MULTILINGUAL_ENGINE
from piper.multilingual_options import SUPPORTED_LANGUAGES

from .controller import SettingsApplyResult, SettingsWindowSnapshot
from .settings_theme import (
    ACCENT,
    BACKGROUND,
    BORDER,
    INPUT,
    TEXT,
    configure_studio_theme,
)


def choose_reference_clip(parent: tk.Misc) -> Optional[Path]:
    selected = filedialog.askopenfilename(
        parent=parent,
        title="Choose Chatterbox reference clip",
        filetypes=[("WAV audio", "*.wav")],
    )
    return Path(selected) if selected else None


def import_managed_reference_clip(source: Path) -> Path:
    from .chatterbox_voice import import_reference_clip

    return import_reference_clip(source)


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
                bool,
            ],
            SettingsApplyResult,
        ],
        on_close: Callable[[], None],
        on_speak_text: Callable[[str], None],
    ) -> None:
        self.window = tk.Toplevel(parent)
        self.window.title("Piper Settings")
        if getattr(parent, "state", lambda: None)() != "withdrawn":
            self.window.transient(parent)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self._on_apply = on_apply
        self._on_close = on_close
        self._on_speak_text = on_speak_text
        self._closed = False
        self.pending_voice_path: Optional[Path] = None
        self.displayed_voice_path = snapshot.piper_voice_path
        self.pending_reference_clip: Optional[str] = None
        self.displayed_reference_clip = snapshot.chatterbox_reference_clip
        self.engine_var = tk.StringVar(value=snapshot.engine)
        self.chatterbox_device_var = tk.StringVar(value=snapshot.chatterbox_device)
        self.multilingual_language_var = tk.StringVar(
            value=SUPPORTED_LANGUAGES[snapshot.multilingual_language]
        )
        double_var = getattr(tk, "DoubleVar", tk.StringVar)
        self.multilingual_exaggeration_var = double_var(
            value=snapshot.multilingual_exaggeration
        )
        self.multilingual_cfg_weight_var = double_var(
            value=snapshot.multilingual_cfg_weight
        )
        self.multilingual_exaggeration_value_var = tk.StringVar(
            value=self._format_slider_value(snapshot.multilingual_exaggeration)
        )
        self.multilingual_cfg_weight_value_var = tk.StringVar(
            value=self._format_slider_value(snapshot.multilingual_cfg_weight)
        )
        boolean_var = getattr(tk, "BooleanVar", tk.StringVar)
        self.chatterbox_custom_voice_var = boolean_var(
            value=snapshot.chatterbox_custom_voice_enabled
        )
        self.reference_clip_name_var = tk.StringVar(value="")
        self.reference_clip_path_var = tk.StringVar(value="")
        self.reference_clip_status_var = tk.StringVar(value="")
        self._reference_import_pending = False
        self.hotkey_var = tk.StringVar(value=snapshot.hotkey)
        self.pitch_var = tk.StringVar(value=f"{snapshot.pitch_percent:g}")
        self.speed_var = tk.StringVar(value=f"{snapshot.speed_percent:g}")
        self.sentence_pause_var = tk.StringVar(value=str(snapshot.sentence_pause_ms))
        self.piper_sentence_streaming_var = tk.StringVar(
            value=("true" if snapshot.piper_sentence_streaming_enabled else "false")
        )
        self.engine_status_var = tk.StringVar(value=snapshot.chatterbox_device_message)
        self._error_vars = {
            key: tk.StringVar(value="")
            for key in (
                "engine",
                "hotkey",
                "pitch",
                "speed",
                "sentence_pause",
                "piper_sentence_streaming",
                "reference_clip",
                "language",
                "exaggeration",
                "cfg_weight",
                "piper_voice",
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
            values=("Piper", "Chatterbox Nano", MULTILINGUAL_ENGINE),
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
        self.nano_voice_frame.columnconfigure(0, weight=1)
        ttk.Label(
            self.nano_voice_frame,
            text="Chatterbox voice",
            style="Muted.Piper.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(10, 5))
        self.chatterbox_device_controls = ttk.Frame(
            self.nano_voice_frame, style="Panel.Piper.TFrame"
        )
        self.chatterbox_device_controls.grid(
            row=1, column=0, sticky="w", pady=(3, 5)
        )
        ttk.Label(
            self.chatterbox_device_controls,
            text="Device",
            style="Muted.Piper.TLabel",
        ).grid(
            row=0, column=0, padx=(0, 12)
        )
        for column, (label, value) in enumerate((("CPU", "cpu"), ("GPU", "cuda")), 1):
            ttk.Radiobutton(
                self.chatterbox_device_controls,
                text=label,
                value=value,
                variable=self.chatterbox_device_var,
            ).grid(row=0, column=column, padx=(0, 10))
        self.multilingual_options_frame = ttk.Frame(
            self.nano_voice_frame, style="Panel.Piper.TFrame"
        )
        self.multilingual_options_frame.columnconfigure(0, weight=1)
        ttk.Label(
            self.multilingual_options_frame,
            text="Language",
            style="Muted.Piper.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(8, 4))
        self.multilingual_language_combo = ttk.Combobox(
            self.multilingual_options_frame,
            textvariable=self.multilingual_language_var,
            values=tuple(SUPPORTED_LANGUAGES.values()),
            state="readonly",
            style="Piper.TCombobox",
            font=("Segoe UI", 10),
        )
        self.multilingual_language_combo.grid(row=1, column=0, sticky="ew")
        self._error_label(self.multilingual_options_frame, "language", 2)
        self.multilingual_exaggeration_scale = self._multilingual_slider(
            self.multilingual_options_frame,
            "Expressiveness",
            self.multilingual_exaggeration_var,
            self.multilingual_exaggeration_value_var,
            0.25,
            2.0,
            3,
        )
        self._error_label(self.multilingual_options_frame, "exaggeration", 5)
        self.multilingual_cfg_weight_scale = self._multilingual_slider(
            self.multilingual_options_frame,
            "Voice/style guidance",
            self.multilingual_cfg_weight_var,
            self.multilingual_cfg_weight_value_var,
            0.0,
            1.0,
            6,
        )
        self._error_label(self.multilingual_options_frame, "cfg_weight", 8)
        ttk.Label(
            self.multilingual_options_frame,
            text="Requires an NVIDIA GPU with CUDA.",
            style="Muted.Piper.TLabel",
            wraplength=310,
        ).grid(row=9, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.import_reference_clip_button = ttk.Button(
            self.nano_voice_frame,
            text="Import reference clip…",
            command=self._choose_reference_clip,
            style="Piper.TButton",
        )
        self.import_reference_clip_button.grid(
            row=3, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Label(
            self.nano_voice_frame,
            textvariable=self.reference_clip_name_var,
            style="Piper.TLabel",
            wraplength=310,
            justify="left",
        ).grid(row=4, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(
            self.nano_voice_frame,
            textvariable=self.reference_clip_path_var,
            style="Muted.Piper.TLabel",
            wraplength=310,
            justify="left",
        ).grid(row=5, column=0, sticky="ew")
        self.chatterbox_custom_voice_checkbutton = ttk.Checkbutton(
            self.nano_voice_frame,
            text="Use custom voice",
            variable=self.chatterbox_custom_voice_var,
            onvalue=True,
            offvalue=False,
            style="Piper.TCheckbutton",
        )
        self.chatterbox_custom_voice_checkbutton.grid(
            row=6, column=0, sticky="w", pady=(8, 0)
        )
        self.reference_clip_error_label = self._error_label(
            self.nano_voice_frame, "reference_clip", 7
        )
        ttk.Label(
            self.nano_voice_frame,
            text=(
                "Choose a clear WAV recording longer than 5 seconds. "
                "Piper keeps a local copy for Chatterbox."
            ),
            style="Muted.Piper.TLabel",
            wraplength=310,
            justify="left",
        ).grid(row=8, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(
            self.nano_voice_frame,
            textvariable=self.reference_clip_status_var,
            style="Muted.Piper.TLabel",
            wraplength=310,
        ).grid(row=9, column=0, sticky="ew", pady=(4, 0))
        self._set_reference_clip_labels(snapshot.chatterbox_reference_clip)
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

    @staticmethod
    def _format_slider_value(value) -> str:
        return f"{float(value):g}"

    def _multilingual_slider(
        self, parent, title, variable, value_variable, minimum, maximum, row
    ):
        ttk.Label(parent, text=title, style="Muted.Piper.TLabel").grid(
            row=row, column=0, sticky="w", pady=(8, 2)
        )
        ttk.Label(
            parent,
            textvariable=value_variable,
            style="Piper.TLabel",
        ).grid(row=row, column=1, sticky="e", pady=(8, 2))
        scale = ttk.Scale(
            parent,
            from_=minimum,
            to=maximum,
            orient="horizontal",
            variable=variable,
            command=lambda value: value_variable.set(
                self._format_slider_value(value)
            ),
            style="Piper.Horizontal.TScale",
        )
        scale.grid(row=row + 1, column=0, columnspan=2, sticky="ew")
        return scale

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
        self._show_frame(self.piper_voice_frame, self.engine_var.get() == "Piper")
        engine = self.engine_var.get()
        chatterbox = engine in {"Chatterbox Nano", MULTILINGUAL_ENGINE}
        self._show_frame(self.nano_voice_frame, chatterbox)
        device_controls = getattr(self, "chatterbox_device_controls", None)
        if device_controls is not None:
            self._show_frame(
                device_controls,
                engine == "Chatterbox Nano",
                row=1,
            )
        multilingual_options = getattr(self, "multilingual_options_frame", None)
        if multilingual_options is not None:
            self._show_frame(
                multilingual_options,
                engine == MULTILINGUAL_ENGINE,
                row=2,
            )

    @staticmethod
    def _show_frame(frame, visible: bool, row: int = 5) -> None:
        if visible:
            frame.grid(row=row, column=0, sticky="ew")
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

    def _set_reference_clip_labels(self, reference: str) -> None:
        path = Path(reference) if reference else None
        self.reference_clip_name_var.set(
            path.name if path else "No reference clip imported"
        )
        self.reference_clip_path_var.set(str(path) if path else "")

    def _choose_reference_clip(self) -> None:
        if self._reference_import_pending or getattr(
            self, "_apply_in_progress", False
        ):
            return
        selected = choose_reference_clip(self.window)
        if selected is None:
            return

        results = Queue(maxsize=1)
        self._reference_import_pending = True
        self.import_reference_clip_button.configure(state="disabled")
        self.reference_clip_status_var.set("Importing reference clip…")

        def import_in_background():
            try:
                results.put((import_managed_reference_clip(selected), None))
            except Exception as error:
                results.put((None, error))

        def poll_import():
            if self._closed:
                return
            try:
                imported_path, error = results.get_nowait()
            except Empty:
                self.window.after(25, poll_import)
                return

            self._reference_import_pending = False
            self.import_reference_clip_button.configure(state="normal")
            if error is not None:
                if isinstance(error, ValueError):
                    detail = str(error).strip()
                    guidance = "Choose a readable WAV clip longer than 5 seconds."
                    message = "%s %s" % (detail, guidance) if detail else guidance
                else:
                    message = (
                        "Piper could not import that WAV file. "
                        "Check that it is readable and try again."
                    )
                self._error_vars["reference_clip"].set(message)
                self.reference_clip_status_var.set("")
                self._render_errors()
                return

            self.pending_reference_clip = str(imported_path)
            self.displayed_reference_clip = self.pending_reference_clip
            self._set_reference_clip_labels(self.displayed_reference_clip)
            self._error_vars["reference_clip"].set("")
            self.reference_clip_status_var.set(
                "Imported. Save changes to use this clip."
            )
            self._render_errors()

        threading.Thread(
            target=import_in_background,
            name="chatterbox-reference-import",
            daemon=True,
        ).start()
        self.window.after(25, poll_import)

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
        if self._reference_import_pending:
            self._error_vars["reference_clip"].set(
                "Wait for the reference clip import to finish before saving."
            )
            self._render_errors()
            return
        arguments = (
            self.engine_var.get(),
            self.hotkey_var.get(),
            self.pitch_var.get(),
            self.speed_var.get(),
            self.pending_voice_path if self.engine_var.get() == "Piper" else None,
            self.sentence_pause_var.get(),
            self.piper_sentence_streaming_var.get() == "true",
        )
        toggle_value = self.chatterbox_custom_voice_var.get()
        custom_voice_enabled = toggle_value is True or toggle_value in ("true", "1")
        reference_clip = (
            self.pending_reference_clip
            if self.pending_reference_clip is not None
            else self.displayed_reference_clip
        )
        owner = getattr(self._on_apply, "__self__", None)
        chatterbox_engine = arguments[0] in {"Chatterbox Nano", MULTILINGUAL_ENGINE}
        if not chatterbox_engine:
            if hasattr(owner, "cancel_nano_settings"):
                result = self._on_apply(
                    *arguments,
                    chatterbox_custom_voice_enabled=custom_voice_enabled,
                    chatterbox_reference_clip=reference_clip,
                )
            else:
                result = self._on_apply(*arguments)
            self._finish_apply(result)
            return
        self._apply_in_progress = True
        self.import_reference_clip_button.configure(state="disabled")
        self._apply_cancel_event = threading.Event()
        self.engine_status_var.set("Preparing %s..." % arguments[0])
        engine = arguments[0]
        device = self.chatterbox_device_var.get()
        multilingual_options = (
            {
                "multilingual_language": self._selected_multilingual_language(),
                "multilingual_exaggeration": float(
                    self.multilingual_exaggeration_var.get()
                ),
                "multilingual_cfg_weight": float(
                    self.multilingual_cfg_weight_var.get()
                ),
            }
            if engine == MULTILINGUAL_ENGINE
            else {}
        )
        results = Queue(maxsize=1)

        def apply_background():
            try:
                if hasattr(owner, "cancel_nano_settings"):
                    options = {
                        "cancel_event": self._apply_cancel_event,
                        "chatterbox_custom_voice_enabled": custom_voice_enabled,
                        "chatterbox_reference_clip": reference_clip,
                    }
                    if engine == "Chatterbox Nano":
                        options["chatterbox_device"] = device
                    else:
                        options.update(multilingual_options)
                    result = self._on_apply(*arguments, **options)
                else:
                    result = self._on_apply(*arguments)
            except Exception:
                message = (
                    "Chatterbox Multilingual V3 is not available. CUDA is required."
                    if engine == MULTILINGUAL_ENGINE
                    else "Chatterbox Nano is not available."
                )
                result = SettingsApplyResult(
                    False, (("engine", message),)
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
            self.import_reference_clip_button.configure(state="normal")
            self.engine_status_var.set("")
            self._finish_apply(result)

        threading.Thread(
            target=apply_background,
            name=(
                "multilingual-settings"
                if engine == MULTILINGUAL_ENGINE
                else "nano-settings"
            ),
            daemon=True,
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

    def _selected_multilingual_language(self) -> str:
        display_name = self.multilingual_language_var.get()
        return next(
            (
                language
                for language, name in SUPPORTED_LANGUAGES.items()
                if name == display_name
            ),
            display_name,
        )

    def _refresh_from_snapshot(self, snapshot: SettingsWindowSnapshot) -> None:
        self.displayed_voice_path = snapshot.piper_voice_path
        self.pending_voice_path = None
        self.pending_reference_clip = None
        self.displayed_reference_clip = snapshot.chatterbox_reference_clip
        self.engine_var.set(snapshot.engine)
        self.chatterbox_device_var.set(snapshot.chatterbox_device)
        self.multilingual_language_var.set(
            SUPPORTED_LANGUAGES[snapshot.multilingual_language]
        )
        self.multilingual_exaggeration_var.set(snapshot.multilingual_exaggeration)
        self.multilingual_cfg_weight_var.set(snapshot.multilingual_cfg_weight)
        self.multilingual_exaggeration_value_var.set(
            self._format_slider_value(snapshot.multilingual_exaggeration)
        )
        self.multilingual_cfg_weight_value_var.set(
            self._format_slider_value(snapshot.multilingual_cfg_weight)
        )
        self.chatterbox_custom_voice_var.set(snapshot.chatterbox_custom_voice_enabled)
        self.engine_status_var.set(snapshot.chatterbox_device_message)
        self.hotkey_var.set(snapshot.hotkey)
        self.pitch_var.set(f"{snapshot.pitch_percent:g}")
        self.speed_var.set(f"{snapshot.speed_percent:g}")
        self.sentence_pause_var.set(str(snapshot.sentence_pause_ms))
        self.piper_sentence_streaming_var.set(
            "true" if snapshot.piper_sentence_streaming_enabled else "false"
        )
        self._set_voice_label(snapshot.piper_voice_path)
        self._set_reference_clip_labels(snapshot.chatterbox_reference_clip)
        self.reference_clip_status_var.set("")
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
