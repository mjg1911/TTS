"""Audio playback using ffplay."""

import shutil
import subprocess
import sys
import threading
from typing import Optional


class AudioPlayer:
    """Plays raw audio using ffplay."""

    def __init__(self, sample_rate: int) -> None:
        """Initializes audio player."""
        self.sample_rate = sample_rate
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._stopped = False
        self._closing = False

    def __enter__(self):
        """Starts ffplay subprocess and returns player."""
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        with self._lock:
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
        return self

    def stop(self) -> None:
        """Terminates active ffplay playback."""
        with self._lock:
            proc = self._proc
            if self._stopped or proc is None:
                return
            self._stopped = True
            if proc.poll() is None:
                try:
                    proc.terminate()
                except OSError:
                    pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stops ffplay subprocess."""
        with self._lock:
            proc = self._proc
            if proc is None:
                return
            self._closing = True
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
            with self._lock:
                if self._proc is proc:
                    self._proc = None
                self._closing = False

    def play(self, audio_bytes: bytes) -> None:
        """Play raw audio and report unexpected ffplay failures."""
        with self._lock:
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
            proc.stdin.write(audio_bytes)
            proc.stdin.flush()
        except (BrokenPipeError, OSError):
            with self._lock:
                if self._stopped or self._closing:
                    return
            raise

    @staticmethod
    def is_available() -> bool:
        """Returns true if ffplay is available."""
        return bool(shutil.which("ffplay"))
