from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Optional, Union


class CommandKind(Enum):
    ACTIVATE = auto()
    CONFIGURE_VOICE = auto()
    OPEN_LOG = auto()
    EXIT = auto()


CommandValue = Union[Path, str]


@dataclass(frozen=True)
class Command:
    kind: CommandKind
    value: Optional[CommandValue] = None
