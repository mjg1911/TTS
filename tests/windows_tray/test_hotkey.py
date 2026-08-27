import pytest

from piper.windows_tray.hotkey import MOD_ALT, VK_F8, parse_hotkey


def test_default_hotkey_parses_to_alt_backtick() -> None:
    spec = parse_hotkey("Alt + `")
    assert spec.canonical == "alt+backtick"
    assert spec.modifiers & MOD_ALT
    assert spec.vk == 0xC0


def test_f8_is_reserved_for_cancel() -> None:
    with pytest.raises(ValueError, match="F8 is reserved"):
        parse_hotkey("f8")


def test_f12_is_reserved_by_windows() -> None:
    with pytest.raises(ValueError, match="F12 is reserved"):
        parse_hotkey("ctrl+f12")


def test_unknown_key_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported key"):
        parse_hotkey("alt+not-a-key")
