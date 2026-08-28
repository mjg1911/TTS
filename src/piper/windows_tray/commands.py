from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Optional


class CommandKind(Enum):
    ACTIVATE = auto()
    CONFIGURE_VOICE = auto()
    TOGGLE_ERROR_SOUNDS = auto()
    OPEN_LOG = auto()
    EXIT = auto()
    CAPTURE_REQUEST = auto()
    CAPTURE_SUCCEEDED = auto()
    CAPTURE_FAILED = auto()
    CANCEL_REQUEST = auto()
    STOP_REQUEST = auto()
    REPLAY_REQUEST = auto()
    WORKER_EVENT = auto()
    SHOW_LAST_TEXT = auto()
    CONFIGURE_HOTKEY = auto()
    HOTKEY_FAILED = auto()
    VOICE_SWITCH_SUCCEEDED = auto()
    VOICE_SWITCH_FAILED = auto()
    SYSTEM_RESUME = auto()


CommandValue = Any


@dataclass(frozen=True)
class Command:
    kind: CommandKind
    value: Optional[CommandValue] = None
