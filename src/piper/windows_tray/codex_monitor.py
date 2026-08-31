from dataclasses import dataclass
from enum import Enum, auto
import os
from pathlib import Path
import threading
from typing import Callable, Dict, Iterable, Optional, Set, Tuple

from .codex_history import CodexCompletedResponse, CodexResponseId, CodexRolloutParser, UnsupportedCodexFormat

POLL_INTERVAL_SECONDS = 0.5
MAX_JSONL_LINE_BYTES = 1_048_576
STOP_JOIN_TIMEOUT_SECONDS = 1.0


class CodexMonitorStatus(Enum):
    RUNNING = auto()
    HISTORY_MISSING = auto()
    TEMPORARILY_UNAVAILABLE = auto()
    UNSUPPORTED_FORMAT = auto()


def codex_sessions_dir(codex_home: Optional[Path] = None) -> Path:
    if codex_home is None:
        configured = os.environ.get("CODEX_HOME")
        codex_home = Path(configured) if configured else Path.home() / ".codex"
    return codex_home / "sessions"


@dataclass
class _FileCursor:
    identity: Tuple[int, int]
    offset: int
    parser: CodexRolloutParser


class _RebaselineRequired(Exception):
    pass


class CodexMonitor:
    def __init__(self, sessions_dir: Path, on_response: Callable[[CodexCompletedResponse], None], on_status: Callable[[CodexMonitorStatus], None], *, poll_interval_seconds: float = POLL_INTERVAL_SECONDS) -> None:
        self._sessions_dir = sessions_dir
        self._on_response = on_response
        self._on_status = on_status
        self._poll_interval_seconds = poll_interval_seconds
        self._cursors: Dict[Path, _FileCursor] = {}
        self._seen: Set[CodexResponseId] = set()
        self._status: Optional[CodexMonitorStatus] = None
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lifecycle_generation = 0
        self._rebaseline_version = 0
        self._rebaseline_requested = False

    @property
    def running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def _paths(self) -> Iterable[Path]:
        if not self._sessions_dir.is_dir():
            raise FileNotFoundError(self._sessions_dir)
        return sorted(self._sessions_dir.rglob("*.jsonl"))

    @staticmethod
    def _identity(path: Path) -> Tuple[int, int]:
        stat = path.stat()
        return int(stat.st_dev), int(stat.st_ino)

    def _open_binary(self, path: Path):
        return path.open("rb")

    def _read_from_cursor(self, path: Path, cursor: _FileCursor) -> list:
        candidates = []
        with self._open_binary(path) as handle:
            handle.seek(cursor.offset)
            while True:
                line_start = cursor.offset
                line = handle.readline(MAX_JSONL_LINE_BYTES + 1)
                if not line:
                    break
                if not line.endswith(b"\n"):
                    if len(line) > MAX_JSONL_LINE_BYTES:
                        while line and not line.endswith(b"\n"):
                            line = handle.readline(MAX_JSONL_LINE_BYTES + 1)
                        cursor.offset = handle.tell()
                        continue
                    break
                if len(line) > MAX_JSONL_LINE_BYTES:
                    cursor.offset = handle.tell()
                    continue
                cursor.offset = handle.tell()
                response = cursor.parser.feed_line(line)
                if response is not None:
                    candidates.append(response)
                if cursor.offset == line_start:
                    break
        return candidates

    def _establish_baseline(self) -> None:
        paths = list(self._paths())
        cursors: Dict[Path, _FileCursor] = {}
        for path in paths:
            cursor = _FileCursor(self._identity(path), 0, CodexRolloutParser())
            self._read_from_cursor(path, cursor)
            cursors[path] = cursor
        self._cursors = cursors

    @staticmethod
    def _newest(candidates: list) -> Optional[CodexCompletedResponse]:
        if not candidates:
            return None
        return max(candidates, key=lambda item: (item.completed_at, item.response_id.conversation_id, item.response_id.turn_id))

    def _poll_once(self) -> Optional[CodexCompletedResponse]:
        paths = list(self._paths())
        current = set(paths)
        if any(path not in current for path in self._cursors):
            raise _RebaselineRequired()
        candidates = []
        for path in paths:
            identity = self._identity(path)
            cursor = self._cursors.get(path)
            if cursor is None:
                cursor = _FileCursor(identity, 0, CodexRolloutParser())
                self._cursors[path] = cursor
            elif cursor.identity != identity:
                raise _RebaselineRequired()
            if path.stat().st_size < cursor.offset:
                raise _RebaselineRequired()
            candidates.extend(self._read_from_cursor(path, cursor))
        unseen = [response for response in candidates if response.response_id not in self._seen]
        for response in unseen:
            self._seen.add(response.response_id)
        return self._newest(unseen)

    def _set_status(self, status: CodexMonitorStatus) -> None:
        if status is self._status:
            return
        self._status = status
        self._on_status(status)

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._lifecycle_generation += 1
            generation = self._lifecycle_generation
            self._rebaseline_version += 1
            self._rebaseline_requested = True
            self._seen.clear()
            self._status = None
            self._wake.clear()
            self._thread = threading.Thread(target=self._run, args=(generation,), name="piper-codex-monitor", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._lifecycle_generation += 1
            thread = self._thread
            self._wake.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=STOP_JOIN_TIMEOUT_SECONDS)
        with self._lock:
            if self._thread is thread and (thread is None or not thread.is_alive()):
                self._thread = None

    def rebaseline(self) -> None:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                return
            self._rebaseline_version += 1
            self._rebaseline_requested = True
            self._wake.set()

    def _run(self, lifecycle_generation: int) -> None:
        unavailable = False
        unsupported = False
        while True:
            with self._lock:
                if lifecycle_generation != self._lifecycle_generation:
                    return
                requested = self._rebaseline_requested
                if requested:
                    self._rebaseline_requested = False
                scan_version = self._rebaseline_version
            if unsupported and not requested:
                self._wake.wait()
                self._wake.clear()
                continue
            try:
                if requested or unavailable:
                    self._establish_baseline()
                    unavailable = False
                    unsupported = False
                    self._set_status(CodexMonitorStatus.RUNNING)
                    continue
                response = self._poll_once()
            except FileNotFoundError:
                unavailable = True
                self._set_status(CodexMonitorStatus.HISTORY_MISSING)
                self._wake.wait(self._poll_interval_seconds); self._wake.clear()
                continue
            except UnsupportedCodexFormat:
                unsupported = True
                self._set_status(CodexMonitorStatus.UNSUPPORTED_FORMAT)
                continue
            except (OSError, _RebaselineRequired):
                unavailable = True
                self._set_status(CodexMonitorStatus.TEMPORARILY_UNAVAILABLE)
                self._wake.wait(self._poll_interval_seconds); self._wake.clear()
                continue
            with self._lock:
                current = lifecycle_generation == self._lifecycle_generation and scan_version == self._rebaseline_version
            if response is not None and current:
                self._on_response(response)
            self._set_status(CodexMonitorStatus.RUNNING)
            self._wake.wait(self._poll_interval_seconds)
            self._wake.clear()
