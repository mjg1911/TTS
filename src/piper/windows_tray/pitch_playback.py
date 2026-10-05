"""Tray-specific raw PCM pitch processing through FFmpeg."""

from collections.abc import Callable
import shutil
import subprocess
import sys
import threading
from typing import Optional, Protocol, Union

from piper.audio_playback import AudioPlayer

from .settings import validate_pitch_percent, validate_speed_percent


class PlaybackPipeline(Protocol):
    def __enter__(self) -> "PlaybackPipeline": ...
    def __exit__(self, exc_type, exc_value, traceback) -> None: ...
    def play(self, audio_bytes: Union[bytes, bytearray]) -> None: ...
    def pause(self) -> None: ...
    def resume(self) -> None: ...
    def stop(self) -> None: ...


def _format_number(value: float) -> str:
    return f"{value:.8f}".rstrip("0").rstrip(".")


def build_pitch_filter(
    sample_rate: int, pitch_percent: float, speed_percent: float
) -> str:
    pitch = validate_pitch_percent(pitch_percent)
    speed = validate_speed_percent(speed_percent)
    pitch_multiplier = 1.0 + pitch / 100.0
    speed_multiplier = 1.0 + speed / 100.0
    return (
        f"asetrate={sample_rate}*{_format_number(pitch_multiplier)},"
        f"aresample={sample_rate},"
        f"atempo={_format_number(1.0 / pitch_multiplier)},"
        f"atempo={_format_number(speed_multiplier)}"
    )


def build_ffmpeg_command(
    sample_rate: int, pitch_percent: float, speed_percent: float
) -> list[str]:
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
        build_pitch_filter(sample_rate, pitch_percent, speed_percent),
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
        speed_percent: float,
        *,
        player_factory: Callable[[int], PlaybackPipeline] = AudioPlayer,
        popen_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
    ) -> None:
        self.sample_rate = sample_rate
        self.pitch_percent = validate_pitch_percent(pitch_percent)
        self.speed_percent = validate_speed_percent(speed_percent)
        self._player_factory = player_factory
        self._popen_factory = popen_factory
        self._player_context: Optional[PlaybackPipeline] = None
        self._player: Optional[PlaybackPipeline] = None
        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None
        self._reader_error: Optional[BaseException] = None
        self._condition = threading.Condition()
        self._reader_done = threading.Event()
        self._stopped = False
        self._paused = False

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
                build_ffmpeg_command(
                    self.sample_rate, self.pitch_percent, self.speed_percent
                ),
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
        self._paused = False
        self._reader_done.clear()
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
        try:
            if proc is None or proc.stdout is None or player is None:
                self._reader_error = RuntimeError("ffmpeg output pipe was not created")
                return

            pending = b""
            read_chunk = getattr(proc.stdout, "read1", proc.stdout.read)
            while True:
                chunk = read_chunk(4096)
                if not chunk:
                    break
                with self._condition:
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
            should_terminate = False
            with self._condition:
                if not self._stopped:
                    self._reader_error = error
                    should_terminate = True
            if should_terminate and proc.poll() is None:
                try:
                    proc.terminate()
                except OSError:
                    pass
        finally:
            self._reader_done.set()
            with self._condition:
                self._condition.notify_all()

    def _raise_reader_error(self) -> None:
        error = self._reader_error
        if error is not None:
            raise RuntimeError(f"ffmpeg output forwarding failed: {error}") from error

    def play(self, audio_bytes: Union[bytes, bytearray]) -> None:
        self._raise_reader_error()
        with self._condition:
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
            with self._condition:
                if self._stopped:
                    return
            raise
        self._raise_reader_error()

    def stop(self) -> None:
        with self._condition:
            if self._stopped:
                self._paused = False
                self._condition.notify_all()
                return
            self._stopped = True
            self._paused = False
            proc = self._proc
            player = self._player
            self._condition.notify_all()
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
        if player is not None:
            player.stop()

    def pause(self) -> None:
        with self._condition:
            if self._stopped or self._reader_done.is_set():
                return
            player = self._player
            if player is None:
                return
            self._paused = True
            pause = getattr(player, "pause", None)
            if callable(pause):
                pause()
            self._condition.notify_all()

    def resume(self) -> None:
        with self._condition:
            if self._stopped or self._reader_done.is_set():
                return
            self._paused = False
            player = self._player
            resume = getattr(player, "resume", None)
            if callable(resume):
                resume()
            self._condition.notify_all()

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        proc = self._proc
        reader = self._reader
        player_context = self._player_context

        returncode = None
        cleanup_error: Optional[BaseException] = None
        try:
            with self._condition:
                stopped = self._stopped
            if proc is not None:
                if not stopped and proc.poll() is None and proc.stdin is not None:
                    try:
                        proc.stdin.close()
                    except OSError as error:
                        cleanup_error = error

            # Keep pause controls active through EOF so shutdown cannot race a
            # pause that would strand the reader before its drain completes.
            with self._condition:
                while not self._stopped and not self._reader_done.is_set():
                    self._condition.wait()
                stopped = self._stopped

            if reader is not None:
                # PCM forwarding is paced in real time, so let the reader drain
                # the final chunk before waiting for ffmpeg to exit.
                reader.join()

            if proc is not None:
                try:
                    returncode = proc.wait(timeout=5)
                except subprocess.TimeoutExpired as error:
                    cleanup_error = error
                    try:
                        proc.kill()
                    except OSError:
                        pass
                    returncode = proc.wait(timeout=5)
        finally:
            if player_context is not None:
                player_context.__exit__(exc_type, exc_value, traceback)
            with self._condition:
                stopped = self._stopped
                self._proc = None
                self._reader = None
                self._player = None
                self._player_context = None
                self._paused = False

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
    speed_percent: float,
) -> PlaybackPipeline:
    pitch = validate_pitch_percent(pitch_percent)
    speed = validate_speed_percent(speed_percent)
    if pitch == 0.0 and speed == 0.0:
        return AudioPlayer(sample_rate)
    if not FfmpegPitchPipeline.is_available():
        raise RuntimeError("ffmpeg is not available")
    return FfmpegPitchPipeline(sample_rate, pitch, speed)
