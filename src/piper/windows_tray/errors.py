"""Stable, concise user-facing errors for recoverable tray failures."""

from enum import Enum, auto


class UserError(Enum):
    NO_TEXT = auto()
    HOTKEY_CONFLICT = auto()
    VOICE_LOAD = auto()
    SYNTHESIS = auto()
    PLAYBACK = auto()
    CLIPBOARD = auto()


USER_MESSAGES = {
    UserError.NO_TEXT: "No text selected or the application did not provide it",
    UserError.HOTKEY_CONFLICT: (
        "That hotkey is already in use. Choose another combination."
    ),
    UserError.VOICE_LOAD: (
        "The selected voice could not be loaded. "
        "The previous voice is still active."
    ),
    UserError.SYNTHESIS: (
        "Speech could not be generated. See the Piper log for details."
    ),
    UserError.PLAYBACK: (
        "Audio playback failed. See the Piper log for details."
    ),
    UserError.CLIPBOARD: "The selected text could not be read from the clipboard.",
}


def user_message(error: UserError) -> str:
    return USER_MESSAGES[error]
