"""Tray-specific raw PCM pitch processing through FFmpeg."""

from collections.abc import Callable
import shutil
import subprocess
import sys
import threading
from typing import Optional, Protocol

from piper.audio_playback import AudioPlayer

from .settings import validate_pitch_percent


class PlaybackPipeline(Protocol):
    def __enter__(self) -> "PlaybackPipeline": ...
    def __exit__(self, exc_type, exc_value, traceback) -> None: ...
    def play(self, audio_bytes: bytes) -> None: ...
    def stop(self) -> None: ...


def _format_number(value: float) -> str:
    return f"{value:.8f}".rstrip("0").rstrip(".")


def build_pitch_filter(sample_rate: int, pitch_percent: float) -> str:
    pitch = validate_pitch_percent(pitch_percent)
    multiplier = 1.0 + pitch / 100.0
    return (
        f"asetrate={sample_rate}*{_format_number(multiplier)},"
        f"aresample={sample_rate},"
        f"atempo={_format_number(1.0 / multiplier)}"
    )


def build_ffmpeg_command(sample_rate: int, pitch_percent: float) -> list[str]:
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "s16le",
        "-ar",
        str(sample_rate),
        "-ac",
        "1",
        "-i",
        "pipe:0",
        "-af",
        build_pitch_filter(sample_rate, pitch_percent),
        "-f",
        "s16le",
        "-ar",
        str(sample_rate),
        "-ac",
        "1",
        "pipe:1",
    ]


class FfmpegPitchPipeline:
    def __init__(
        self,
        sample_rate: int,
        pitch_percent: float,
        *,
        player_factory: Callable[[int], PlaybackPipeline] = AudioPlayer,
        popen_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
    ) -> None:
        self.sample_rate = sample_rate
        self.pitch_percent = validate_pitch_percent(pitch_percent)
        self._player_factory = player_factory
        self._popen_factory = popen_factory
        self._player_context: Optional[PlaybackPipeline] = None
        self._player: Optional[PlaybackPipeline] = None
        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._reader_error: Optional[BaseException] = None
        self._lock = threading.Lock()
        self._stopped = False

    @staticmethod
    def is_available() -> bool:
        return bool(shutil.which("ffmpeg"))

    def __enter__(self) -> "FfmpegPitchPipeline":
        player_context = self._player_factory(self.sample_rate)
        player = player_context.__enter__()
        creationflags = (
            subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )
        try:
            proc = self._popen_factory(
                build_ffmpeg_command(self.sample_rate, self.pitch_percent),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
                shell=False,
            )
        except BaseException:
            player_context.__exit__(*sys.exc_info())
            raise

        self._player_context = player_context
        self._player = player
        self._proc = proc
        self._stopped = False
        self._reader_error = None
        self._reader = threading.Thread(
            target=self._drain_output,
            name="piper-ffmpeg-pitch",
            daemon=True,
        )
        self._reader.start()
        return self

    def _drain_output(self) -> None:
        proc = self._proc
        player = self._player
        if proc is None or proc.stdout is None or player is None:
            self._reader_error = RuntimeError("ffmpeg output pipe was not created")
            return

        pending = b""
        try:
            read_chunk = getattr(proc.stdout, "read1", proc.stdout.read)
            while True:
                chunk = read_chunk(4096)
                if not chunk:
                    break
                with self._lock:
                    if self._stopped:
                        return
                data = pending + chunk
                even_length = len(data) - (len(data) % 2)
                if even_length:
                    player.play(data[:even_length])
                pending = data[even_length:]
            if pending:
                raise RuntimeError("ffmpeg produced malformed s16le output")
        except BaseException as error:
            with self._lock:
                if not self._stopped:
                    self._reader_error = error

    def _raise_reader_error(self) -> None:
        error = self._reader_error
        if error is not None:
            raise RuntimeError(f"ffmpeg output forwarding failed: {error}") from error

    def play(self, audio_bytes: bytes) -> None:
        self._raise_reader_error()
        with self._lock:
            if self._stopped:
                return
            proc = self._proc
            if proc is None or proc.stdin is None:
                raise RuntimeError("ffmpeg is not running")
            returncode = proc.poll()
            if returncode is not None:
                raise RuntimeError(f"ffmpeg exited unexpectedly with code {returncode}")

        try:
            proc.stdin.write(audio_bytes)
            proc.stdin.flush()
        except (BrokenPipeError, OSError):
            with self._lock:
                if self._stopped:
                    return
            raise
        self._raise_reader_error()

    def stop(self) -> None:
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            proc = self._proc
            player = self._player
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
        if player is not None:
            player.stop()

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        proc = self._proc
        reader = self._reader
        player_context = self._player_context
        with self._lock:
            stopped = self._stopped

        returncode = None
        cleanup_error: Optional[BaseException] = None
        try:
            if proc is not None:
                if not stopped and proc.poll() is None and proc.stdin is not None:
                    try:
                        proc.stdin.close()
                    except OSError as error:
                        cleanup_error = error
                try:
                    returncode = proc.wait(timeout=5)
                except subprocess.TimeoutExpired as error:
                    cleanup_error = error
                    try:
                        proc.kill()
                    except OSError:
                        pass
                    returncode = proc.wait(timeout=5)
            if reader is not None:
                reader.join(timeout=5)
                if reader.is_alive() and cleanup_error is None:
                    cleanup_error = RuntimeError("ffmpeg output reader did not stop")
        finally:
            if player_context is not None:
                player_context.__exit__(exc_type, exc_value, traceback)
            self._proc = None
            self._reader = None
            self._player = None
            self._player_context = None

        if exc_type is not None or stopped:
            return
        if cleanup_error is not None:
            raise cleanup_error
        self._raise_reader_error()
        if returncode not in (None, 0):
            raise RuntimeError(f"ffmpeg exited unexpectedly with code {returncode}")


def create_playback_pipeline(
    sample_rate: int,
    pitch_percent: float,
) -> PlaybackPipeline:
    pitch = validate_pitch_percent(pitch_percent)
    if pitch == 0.0:
        return AudioPlayer(sample_rate)
    if not FfmpegPitchPipeline.is_available():
        raise RuntimeError("ffmpeg is not available")
    return FfmpegPitchPipeline(sample_rate, pitch)
