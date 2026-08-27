from piper.windows_tray.errors import (
    USER_MESSAGES,
    UserError,
    user_message,
)


def test_user_error_messages_are_stable() -> None:
    assert user_message(UserError.NO_TEXT) == (
        "No text selected or the application did not provide it"
    )
    assert user_message(UserError.HOTKEY_CONFLICT) == (
        "That hotkey is already in use. Choose another combination."
    )
    assert user_message(UserError.HOTKEY_INVALID) == (
        "That hotkey is not valid. Choose another combination."
    )
    assert user_message(UserError.VOICE_LOAD) == (
        "The selected voice could not be loaded. "
        "The previous voice is still active."
    )
    assert user_message(UserError.SYNTHESIS) == (
        "Speech could not be generated. See the Piper log for details."
    )
    assert user_message(UserError.PLAYBACK) == (
        "Audio playback failed. See the Piper log for details."
    )
    assert user_message(UserError.CLIPBOARD) == (
        "The selected text could not be read from the clipboard."
    )

    assert set(USER_MESSAGES) == set(UserError)
