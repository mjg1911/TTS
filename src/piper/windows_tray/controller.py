from dataclasses import dataclass
from queue import Empty, Queue
from typing import Optional

from .commands import Command, CommandKind


@dataclass
class AppState:
    last_text: Optional[str] = None
    shutting_down: bool = False


class Controller:
    def __init__(self) -> None:
        self.state = AppState()
        self._commands = Queue()

    def enqueue(self, command: Command) -> None:
        self._commands.put(command)

    def drain_once(self) -> Optional[Command]:
        try:
            command = self._commands.get_nowait()
        except Empty:
            return None
        if command.kind is CommandKind.EXIT:
            self.state.shutting_down = True
        return command
