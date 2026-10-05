"""Scoped ttk styling for the Piper speech workspace."""

from tkinter import ttk

BACKGROUND = "#11181c"
PANEL = "#1b252b"
INPUT = "#121c22"
TEXT = "#edf4f4"
MUTED = "#a1b3bb"
ACCENT = "#70dfc0"
BORDER = "#32434c"
ERROR = "#ffb5a7"


def configure_studio_theme(window):
    style = ttk.Style(window)
    # Clam allows custom colors on Windows; all overrides use Piper names.
    if "piper-studio" not in style.theme_names():
        style.theme_create("piper-studio", parent="clam")
    style.theme_use("piper-studio")
    body = ("Segoe UI", 10)
    style.configure("Piper.TFrame", background=BACKGROUND)
    style.configure("Panel.Piper.TFrame", background=PANEL)
    style.configure("Piper.TLabel", background=PANEL, foreground=TEXT, font=body)
    style.configure("Muted.Piper.TLabel", foreground=MUTED, font=("Segoe UI", 9))
    style.configure("Error.Piper.TLabel", foreground=ERROR, font=("Segoe UI", 9))
    style.configure("Section.Piper.TLabel", font=("Segoe UI", 11, "bold"))
    style.configure(
        "Title.Piper.TLabel", background=BACKGROUND, font=("Segoe UI", 24, "bold")
    )
    style.configure("Subtitle.Piper.TLabel", background=BACKGROUND, foreground=MUTED)
    style.configure(
        "Badge.Piper.TLabel",
        background=PANEL,
        foreground=ACCENT,
        padding=(12, 6),
        font=("Segoe UI", 9, "bold"),
    )
    for name in ("Piper.TEntry", "Piper.TCombobox"):
        style.configure(
            name,
            fieldbackground=INPUT,
            background=PANEL,
            foreground=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            insertcolor=TEXT,
            padding=7,
            font=body,
            arrowsize=13,
            arrowcolor=MUTED,
        )
        style.map(
            name,
            bordercolor=[("focus", ACCENT)],
            fieldbackground=[("readonly", INPUT)],
            foreground=[("disabled", MUTED), ("readonly", TEXT)],
            selectbackground=[("!disabled", "#315e57")],
            selectforeground=[("!disabled", TEXT)],
        )
    for name, background, foreground in (
        ("Piper.TButton", "#293940", TEXT),
        ("Primary.Piper.TButton", ACCENT, "#10251f"),
    ):
        style.configure(
            name,
            background=background,
            foreground=foreground,
            bordercolor=background,
            lightcolor=background,
            darkcolor=background,
            padding=(16, 9),
            font=("Segoe UI", 10, "bold"),
            focusthickness=2,
            focuscolor=foreground,
        )
        style.map(
            name,
            background=[
                ("disabled", "#293940"),
                ("active", "#96ecd3" if name == "Primary.Piper.TButton" else "#3b515b"),
            ],
            foreground=[("disabled", MUTED)],
        )
    style.configure(
        "Piper.TCheckbutton",
        background=PANEL,
        foreground=TEXT,
        font=("Segoe UI", 9),
        indicatorbackground=INPUT,
        indicatorforeground=ACCENT,
        focuscolor=ACCENT,
        padding=4,
    )
    style.map(
        "Piper.TCheckbutton",
        background=[("active", PANEL)],
        indicatorbackground=[("selected", ACCENT)],
    )
    # Present device choices as themed buttons while retaining radio semantics.
    style.layout(
        "Device.Piper.TRadiobutton",
        [
            (
                "Button.border",
                {
                    "sticky": "nswe",
                    "children": [
                        (
                            "Button.focus",
                            {
                                "sticky": "nswe",
                                "children": [
                                    (
                                        "Button.padding",
                                        {
                                            "sticky": "nswe",
                                            "children": [
                                                (
                                                    "Radiobutton.label",
                                                    {"sticky": "nswe"},
                                                ),
                                            ],
                                        },
                                    ),
                                ],
                            },
                        ),
                    ],
                },
            )
        ],
    )
    style.configure(
        "Device.Piper.TRadiobutton",
        background=INPUT,
        foreground=MUTED,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        focuscolor=TEXT,
        focusthickness=1,
        padding=(12, 8),
        anchor="center",
        font=("Segoe UI", 10, "bold"),
    )
    for option in ("background", "bordercolor", "lightcolor", "darkcolor"):
        style.map(
            "Device.Piper.TRadiobutton",
            **{
                option: [
                    ("disabled", PANEL),
                    ("selected", ACCENT),
                    ("active", "#293940"),
                ]
            },
        )
    style.map(
        "Device.Piper.TRadiobutton",
        foreground=[("disabled", MUTED), ("selected", "#10251f"), ("active", TEXT)],
        focuscolor=[("selected", "#10251f")],
    )
    style.configure(
        "Piper.Vertical.TScrollbar",
        background=BORDER,
        troughcolor=PANEL,
        bordercolor=PANEL,
        arrowcolor=MUTED,
        lightcolor=PANEL,
        darkcolor=PANEL,
        arrowsize=11,
    )
    style.map("Piper.Vertical.TScrollbar", background=[("active", "#506873")])
    style.configure(
        "Piper.Horizontal.TScale",
        background=ACCENT,
        troughcolor=INPUT,
        bordercolor=PANEL,
        lightcolor=ACCENT,
        darkcolor=ACCENT,
    )
    style.map("Piper.Horizontal.TScale", background=[("active", "#96ecd3")])
    style.configure(
        "Help.Piper.TButton",
        background=PANEL,
        foreground=ACCENT,
        bordercolor=BORDER,
        padding=(3, 0),
        font=("Segoe UI", 9, "bold"),
    )
    style.configure(
        "Piper.Horizontal.TProgressbar",
        background=ACCENT,
        troughcolor=INPUT,
        bordercolor=BACKGROUND,
        lightcolor=ACCENT,
        darkcolor=ACCENT,
    )
    window.configure(background=BACKGROUND)
    window.option_add("*TCombobox*Listbox.background", INPUT)
    window.option_add("*TCombobox*Listbox.foreground", TEXT)
    window.option_add("*TCombobox*Listbox.selectBackground", "#315e57")
    window.option_add("*TCombobox*Listbox.selectForeground", TEXT)
    window.option_add("*TCombobox*Listbox.font", body)
