import io
import subprocess
import threading
import time

import pytest

from piper.audio_playback import AudioPlayer
from piper.windows_tray import pitch_playback


@pytest.mark.parametrize(
    ("pitch", "speed", "expected"),
    [
        (
            26,
            0,
            "asetrate=22050*1.26,aresample=22050,atempo=0.79365079,atempo=1",
        ),
        (-50, 0, "asetrate=22050*0.5,aresample=22050,atempo=2,atempo=1"),
        (100, 0, "asetrate=22050*2,aresample=22050,atempo=0.5,atempo=1"),
        (0, 50, "asetrate=22050*1,aresample=22050,atempo=1,atempo=1.5"),
        (
            26,
            50,
            "asetrate=22050*1.26,aresample=22050,atempo=0.79365079,atempo=1.5",
        ),
    ],
)
def test_build_pitch_filter_uses_rate_shift_and_tempo_compensation(
    pitch, speed, expected
) -> None:
    assert pitch_playback.build_pitch_filter(22050, pitch, speed) == expected


def test_build_ffmpeg_command_is_explicit_raw_pcm_on_both_sides() -> None:
    command = pitch_playback.build_ffmpeg_command(22050, 26, 50)

    assert command == [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "s16le",
        "-ar", "22050", "-ac", "1", "-i", "pipe:0", "-af",
        "asetrate=22050*1.26,aresample=22050,atempo=0.79365079,atempo=1.5", "-f",
        "s16le", "-ar", "22050", "-ac", "1", "pipe:1",
    ]


class RecordingInput:
    def __init__(self) -> None:
        self.data = bytearray()
        self.closed = False

    def write(self, data: bytes) -> None:
        if self.closed:
            raise BrokenPipeError("stdin closed")
        self.data.extend(data)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class FakeProcess:
    def __init__(self, output: bytes = b"\x00\x00") -> None:
        self.stdin = RecordingInput()
        self.stdout = io.BytesIO(output)
        self.returncode = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        del timeout
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


class HangingProcess(FakeProcess):
    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("ffmpeg", timeout)
        return super().wait(timeout)


class FakePlayer:
    def __init__(self) -> None:
        self.played = []
        self.stopped = False
        self.exited = False

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        self.exited = True

    def play(self, data: bytes) -> None:
        if not self.stopped:
            self.played.append(data)

    def stop(self) -> None:
        self.stopped = True


class FailingPlayer(FakePlayer):
    def __init__(self) -> None:
        super().__init__()
        self.failed = threading.Event()

    def play(self, data: bytes) -> None:
        del data
        self.failed.set()
        raise RuntimeError("speaker failed")


def test_pipeline_starts_one_ffmpeg_process_and_streams_all_chunks() -> None:
    process = FakeProcess(output=b"\x01\x00\x02\x00")
    player = FakePlayer()
    popen_calls = []

    def popen(command, **kwargs):
        popen_calls.append((command, kwargs))
        return process

    pipeline = pitch_playback.FfmpegPitchPipeline(
        22050,
        26,
        50,
        player_factory=lambda _sample_rate: player,
        popen_factory=popen,
    )
    with pipeline:
        pipeline.play(b"first")
        pipeline.play(b"second")

    assert len(popen_calls) == 1
    assert bytes(process.stdin.data) == b"firstsecond"
    assert b"".join(player.played) == b"\x01\x00\x02\x00"
    assert popen_calls[0][1]["stdin"] is subprocess.PIPE
    assert popen_calls[0][1]["stdout"] is subprocess.PIPE
    assert popen_calls[0][1]["stderr"] is subprocess.DEVNULL
    assert popen_calls[0][1]["shell"] is False
    assert player.exited is True


def test_reader_failure_terminates_ffmpeg_and_preserves_playback_error() -> None:
    process = HangingProcess(output=b"\x01\x00")
    player = FailingPlayer()
    pipeline = pitch_playback.FfmpegPitchPipeline(
        22050,
        26,
        50,
        player_factory=lambda _sample_rate: player,
        popen_factory=lambda *_args, **_kwargs: process,
    )

    with pytest.raises(RuntimeError, match="speaker failed"):
        with pipeline:
            assert player.failed.wait(timeout=1)

    assert process.terminated is True


def test_stop_terminates_ffmpeg_and_stops_forwarding_to_ffplay() -> None:
    process = FakeProcess(output=b"\x01\x00\x02\x00")
    player = FakePlayer()
    pipeline = pitch_playback.FfmpegPitchPipeline(
        22050,
        26,
        50,
        player_factory=lambda _sample_rate: player,
        popen_factory=lambda *_args, **_kwargs: process,
    )

    pipeline.__enter__()
    pipeline.stop()
    pipeline.play(b"stale")
    pipeline.__exit__(None, None, None)

    assert process.terminated is True
    assert player.stopped is True
    assert b"stale" not in bytes(process.stdin.data)


def test_malformed_odd_length_ffmpeg_output_is_a_failure() -> None:
    process = FakeProcess(output=b"\x01")
    pipeline = pitch_playback.FfmpegPitchPipeline(
        22050,
        26,
        50,
        player_factory=lambda _sample_rate: FakePlayer(),
        popen_factory=lambda *_args, **_kwargs: process,
    )

    with pytest.raises(RuntimeError, match="malformed s16le"):
        with pipeline:
            pipeline.play(b"audio")


def test_nonzero_ffmpeg_exit_is_a_failure() -> None:
    process = FakeProcess()
    process.returncode = 4
    pipeline = pitch_playback.FfmpegPitchPipeline(
        22050,
        26,
        50,
        player_factory=lambda _sample_rate: FakePlayer(),
        popen_factory=lambda *_args, **_kwargs: process,
    )

    with pytest.raises(RuntimeError, match="ffmpeg exited unexpectedly with code 4"):
        with pipeline:
            pass


def test_zero_pitch_returns_direct_audio_player_without_checking_ffmpeg(monkeypatch) -> None:
    monkeypatch.setattr(
        pitch_playback.FfmpegPitchPipeline,
        "is_available",
        lambda: (_ for _ in ()).throw(AssertionError("ffmpeg should not be checked")),
    )

    pipeline = pitch_playback.create_playback_pipeline(22050, 0, 0)

    assert isinstance(pipeline, AudioPlayer)


def test_nonzero_pitch_requires_ffmpeg(monkeypatch) -> None:
    monkeypatch.setattr(pitch_playback.FfmpegPitchPipeline, "is_available", lambda: False)

    with pytest.raises(RuntimeError, match="ffmpeg is not available"):
        pitch_playback.create_playback_pipeline(22050, 26, 0)


@pytest.mark.parametrize(
    "build",
    [
        lambda: pitch_playback.build_pitch_filter(22050, 0, 100.001),
        lambda: pitch_playback.build_ffmpeg_command(22050, 0, 100.001),
        lambda: pitch_playback.FfmpegPitchPipeline(22050, 0, 100.001),
        lambda: pitch_playback.create_playback_pipeline(22050, 0, 100.001),
    ],
)
def test_invalid_speed_is_rejected_by_every_playback_entry_point(build) -> None:
    with pytest.raises(ValueError):
        build()


def test_speed_only_requires_ffmpeg(monkeypatch) -> None:
    monkeypatch.setattr(
        pitch_playback.FfmpegPitchPipeline, "is_available", lambda: False
    )

    with pytest.raises(RuntimeError, match="ffmpeg is not available"):
        pitch_playback.create_playback_pipeline(22050, 0, 50)


class BlockingOutput:
    def __init__(self) -> None:
        self.calls = 0
        self.release = threading.Event()

    def read(self, _size: int) -> bytes:
        self.calls += 1
        if self.calls == 1:
            return b"\x01\x00"
        if self.calls == 2:
            self.release.wait(timeout=2)
            return b"\x02\x00"
        return b""


def test_reader_discards_output_released_after_stop() -> None:
    process = FakeProcess()
    process.stdout = BlockingOutput()
    player = FakePlayer()
    pipeline = pitch_playback.FfmpegPitchPipeline(
        22050,
        26,
        50,
        player_factory=lambda _sample_rate: player,
        popen_factory=lambda *_args, **_kwargs: process,
    )

    pipeline.__enter__()
    deadline = time.monotonic() + 1.0
    while not player.played and time.monotonic() < deadline:
        time.sleep(0.01)
    assert player.played == [b"\x01\x00"]
    pipeline.stop()
    process.stdout.release.set()
    pipeline.__exit__(None, None, None)

    assert player.played == [b"\x01\x00"]
