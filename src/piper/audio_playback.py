"""Audio playback using ffplay."""

import shutil
import subprocess
import sys
import threading
import time
from typing import Optional, Union


_PCM_WRITE_CHUNK_SIZE = 4096


class AudioPlayer:
    """Plays raw audio using ffplay."""

    def __init__(self, sample_rate: int) -> None:
        """Initializes audio player."""
        self.sample_rate = sample_rate
        self._proc: Optional[subprocess.Popen] = None
        self._condition = threading.Condition()
        self._write_lock = threading.Lock()
        self._stopped = False
        self._closing = False
        self._paused = False
        self._next_write_at: Optional[float] = None

    def __enter__(self):
        """Starts ffplay subprocess and returns player."""
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        with self._condition:
            self._proc = subprocess.Popen(
                [
                    "ffplay",
                    "-nodisp",
                    "-autoexit",
                    "-f",
                    "s16le",
                    "-sample_rate",
                    str(self.sample_rate),
                    "-ch_layout",
                    "mono",
                    "-",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
            self._stopped = False
            self._closing = False
            self._paused = False
            self._next_write_at = None
        return self

    def pause(self) -> None:
        """Pause output before the next PCM chunk is written."""
        with self._condition:
            if self._proc is None or self._stopped or self._closing:
                return
            self._paused = True
            self._condition.notify_all()

    def resume(self) -> None:
        """Resume output and wake any writer waiting at the pause gate."""
        with self._condition:
            if self._paused and self._next_write_at is not None:
                now = time.monotonic()
                if now >= self._next_write_at:
                    # Keep an unexpired chunk deadline; rebase once it drains.
                    self._next_write_at = now
            self._paused = False
            self._condition.notify_all()

    def stop(self) -> None:
        """Terminates active ffplay playback."""
        with self._condition:
            proc = self._proc
            if self._stopped or proc is None:
                self._paused = False
                self._condition.notify_all()
                return
            self._stopped = True
            self._paused = False
            self._condition.notify_all()
            if proc.poll() is None:
                try:
                    proc.terminate()
                except OSError:
                    pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stops ffplay subprocess."""
        with self._condition:
            proc = self._proc
            if proc is None:
                return
            self._closing = True
            self._paused = False
            self._condition.notify_all()
        try:
            if proc.poll() is None and proc.stdin:
                try:
                    proc.stdin.close()
                except Exception:
                    pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except OSError:
                    pass
        finally:
            with self._condition:
                if self._proc is proc:
                    self._proc = None
                self._closing = False

    def _wait_for_write_time(self, proc: subprocess.Popen) -> Optional[float]:
        with self._condition:
            while True:
                while self._paused and not self._stopped and not self._closing:
                    self._condition.wait()
                if self._stopped or self._closing or self._proc is not proc:
                    return None

                now = time.monotonic()
                deadline = self._next_write_at
                if deadline is None:
                    return now
                if now >= deadline:
                    max_lateness = _PCM_WRITE_CHUNK_SIZE / (self.sample_rate * 2)
                    # Rebase after a full chunk of lag to avoid a catch-up burst.
                    if now - deadline > max_lateness:
                        return now
                    return deadline
                self._condition.wait(timeout=deadline - now)

    def play(self, audio_bytes: Union[bytes, bytearray]) -> None:
        """Play raw audio and report unexpected ffplay failures."""
        with self._condition:
            proc = self._proc
            if self._stopped or self._closing:
                return
            if proc is None or proc.stdin is None:
                raise RuntimeError("ffplay is not running")
            returncode = proc.poll()
            if returncode is not None:
                raise RuntimeError(
                    f"ffplay exited unexpectedly with code {returncode}"
                )

        try:
            with self._write_lock:
                with self._condition:
                    if self._stopped or self._closing or self._proc is not proc:
                        return

                if not audio_bytes:
                    proc.stdin.flush()
                    return

                for offset in range(0, len(audio_bytes), _PCM_WRITE_CHUNK_SIZE):
                    chunk = audio_bytes[offset : offset + _PCM_WRITE_CHUNK_SIZE]
                    chunk_started_at = self._wait_for_write_time(proc)
                    if chunk_started_at is None:
                        return

                    proc.stdin.write(chunk)
                    proc.stdin.flush()

                    chunk_duration = len(chunk) / (self.sample_rate * 2)
                    next_write_at = max(
                        chunk_started_at + chunk_duration,
                        time.monotonic(),
                    )
                    with self._condition:
                        if (
                            self._proc is proc
                            and not self._stopped
                            and not self._closing
                        ):
                            self._next_write_at = next_write_at

                # The last chunk also needs its scheduled playback interval before
                # play() returns and allows a context manager to close ffplay.
                if self._wait_for_write_time(proc) is None:
                    return
        except (BrokenPipeError, OSError):
            with self._condition:
                if self._stopped or self._closing or self._proc is not proc:
                    return
            raise

    @staticmethod
    def is_available() -> bool:
        """Returns true if ffplay is available."""
        return bool(shutil.which("ffplay"))
