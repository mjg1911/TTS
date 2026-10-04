"""Record a hotkey from key events received by a focused settings entry."""

from __future__ import annotations

from typing import Any, Callable, Optional

from .hotkey import parse_hotkey


_STATE_SHIFT = 0x0001
_STATE_CONTROL = 0x0004
# Tk's Windows Alt state is Mod1 (0x20000); 0x8 is Lock on Windows.
_STATE_ALT = 0x20000

_MODIFIER_KEYSYMS = {
    "alt_l": "alt",
    "alt_r": "alt",
    "control_l": "ctrl",
    "control_r": "ctrl",
    "shift_l": "shift",
    "shift_r": "shift",
    "super_l": "win",
    "super_r": "win",
    "win_l": "win",
    "win_r": "win",
    "windows_l": "win",
    "windows_r": "win",
}


class ShortcutRecorder:
    """Capture one supported hotkey using events from a Tk entry widget."""

    def __init__(
        self,
        entry: Any,
        variable: Any,
        status_variable: Any,
        on_start: Optional[Callable[[], bool]] = None,
        on_finish: Optional[Callable[[], bool]] = None,
    ) -> None:
        self.entry = entry
        self.variable = variable
        self.status_variable = status_variable
        self._on_start = on_start
        self._on_finish = on_finish
        self._recording = False
        self._original_value = ""
        self._held_modifiers: set[str] = set()
        self.entry.bind("<KeyPress>", self.handle_key, add="+")
        self.entry.bind("<KeyRelease>", self._handle_key_release, add="+")
        self.entry.bind("<FocusOut>", self._handle_focus_out, add="+")
        self.entry.bind("<Button-1>", self._activate_from_click, add="+")
        self.entry.bind("<Return>", self._activate_from_key, add="+")
        self.entry.bind("<space>", self._activate_from_key, add="+")

    @property
    def is_recording(self) -> bool:
        return self._recording

    def start(self) -> None:
        if self._recording:
            return
        if str(self.entry.cget("state")).lower() == "disabled":
            return
        try:
            can_start = self._on_start is None or self._on_start()
        except Exception:
            can_start = False
        if not can_start:
            self.status_variable.set(
                "The current shortcut could not be paused. Try again."
            )
            return
        self._original_value = self.variable.get()
        self._held_modifiers.clear()
        self._recording = True
        self.status_variable.set(
            "Press a shortcut combination. Press Escape to cancel."
        )
        self.entry.focus_set()

    def cancel(self) -> None:
        if not self._recording:
            return
        self.variable.set(self._original_value)
        if self._finish():
            self.status_variable.set("Shortcut recording cancelled.")
        else:
            self.status_variable.set(
                "Recording cancelled, but the previous shortcut could not be restored."
            )

    def handle_key(self, event: Any) -> str | None:
        if not self._recording:
            return None

        keysym = str(getattr(event, "keysym", ""))
        modifier = _MODIFIER_KEYSYMS.get(keysym.lower())
        if modifier:
            self._held_modifiers.add(modifier)
            return "break"

        if keysym.lower() == "escape":
            self.cancel()
            return "break"

        modifiers = self._current_modifiers(getattr(event, "state", 0))
        key = self._key_token(keysym)
        # Windows Tk reports symbols such as "exclam" for Shift+1, while
        # RegisterHotKey needs the digit's virtual key.
        keycode = getattr(event, "keycode", 0)
        if key is None and isinstance(keycode, int) and 0x30 <= keycode <= 0x39:
            key = chr(keycode)
        if key is None:
            self.status_variable.set(
                f"That key cannot be used: unsupported key: {keysym.lower()}"
            )
            return "break"

        candidate = "+".join([*self._ordered_modifiers(modifiers), key])
        try:
            spec = parse_hotkey(candidate)
        except ValueError as exc:
            self.status_variable.set(f"That shortcut cannot be used: {exc}")
            return "break"

        self.variable.set(spec.canonical)
        if self._finish():
            self.status_variable.set("")
        else:
            self.status_variable.set(
                "Shortcut recorded, but the previous shortcut could not be restored."
            )
        return "break"

    def _handle_key_release(self, event: Any) -> str | None:
        if not self._recording:
            return None
        modifier = _MODIFIER_KEYSYMS.get(str(getattr(event, "keysym", "")).lower())
        if modifier:
            self._held_modifiers.discard(modifier)
        return "break"

    def _handle_focus_out(self, _event: Any) -> str | None:
        self.cancel()
        return "break"

    def _activate_from_click(self, _event: Any) -> str:
        if not self._recording:
            self.start()
        return "break"

    def _activate_from_key(self, event: Any) -> str:
        if self._recording:
            self.handle_key(event)
        else:
            self.start()
        return "break"

    def _current_modifiers(self, state: Any) -> set[str]:
        try:
            state = int(state)
        except (TypeError, ValueError):
            state = 0
        modifiers = set(self._held_modifiers)
        if state & _STATE_CONTROL:
            modifiers.add("ctrl")
        if state & _STATE_ALT:
            modifiers.add("alt")
        if state & _STATE_SHIFT:
            modifiers.add("shift")
        return modifiers

    @staticmethod
    def _key_token(keysym: str) -> str | None:
        normalized = keysym.lower()
        if normalized in {"grave", "asciitilde", "quoteleft", "tilde", "`", "~"}:
            return "backtick"
        if len(normalized) == 1 and (normalized.isalpha() or normalized.isdigit()):
            return normalized
        if normalized.startswith("f") and normalized[1:].isdigit():
            return normalized
        return None

    @staticmethod
    def _ordered_modifiers(modifiers: set[str]) -> list[str]:
        return [
            modifier
            for modifier in ("ctrl", "alt", "shift", "win")
            if modifier in modifiers
        ]

    def _finish(self) -> bool:
        self._recording = False
        self._held_modifiers.clear()
        if self._on_finish is None:
            return True
        try:
            return bool(self._on_finish())
        except Exception:
            return False
