from dataclasses import dataclass
from typing import Optional


MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
VK_F8 = 0x77
VK_F12 = 0x7B

_MODIFIERS = {
    "alt": MOD_ALT,
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "windows": MOD_WIN,
}
_KEYS = {
    "backtick": 0xC0,
    "`": 0xC0,
    "tilde": 0xC0,
    "~": 0xC0,
    **{chr(code).lower(): code for code in range(ord("A"), ord("Z") + 1)},
    **{str(number): ord(str(number)) for number in range(10)},
    **{f"f{number}": 0x6F + number for number in range(1, 13)},
}


@dataclass(frozen=True)
class HotkeySpec:
    modifiers: int
    vk: int
    canonical: str


def parse_hotkey(value: str) -> HotkeySpec:
    tokens = [token.strip().lower() for token in value.replace(" ", "").split("+")]
    if not tokens or any(not token for token in tokens):
        raise ValueError("hotkey is empty")

    modifiers = 0
    key_token: Optional[str] = None
    canonical_modifiers: list[str] = []
    for token in tokens:
        if token in _MODIFIERS:
            bit = _MODIFIERS[token]
            if modifiers & bit:
                raise ValueError("duplicate modifier")
            modifiers |= bit
            canonical_modifiers.append(
                "ctrl" if bit == MOD_CONTROL else "win" if bit == MOD_WIN else token
            )
        elif key_token is None:
            key_token = token
        else:
            raise ValueError("hotkey must contain exactly one non-modifier key")

    if key_token is None or key_token not in _KEYS:
        raise ValueError(f"unsupported key: {key_token}")
    vk = _KEYS[key_token]
    if vk == VK_F8:
        raise ValueError("F8 is reserved for cancellation")
    if vk == VK_F12:
        raise ValueError("F12 is reserved by Windows")

    key_name = "backtick" if vk == 0xC0 else key_token
    order = {"ctrl": 0, "alt": 1, "shift": 2, "win": 3}
    canonical_modifiers = sorted(set(canonical_modifiers), key=order.__getitem__)
    canonical = "+".join([*canonical_modifiers, key_name])
    return HotkeySpec(modifiers, vk, canonical)
