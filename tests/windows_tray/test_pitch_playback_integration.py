import math
import shutil
import struct
import subprocess

import pytest

from piper.windows_tray.pitch_playback import build_ffmpeg_command


SAMPLE_RATE = 22050
DURATION_SECONDS = 0.5
INPUT_FREQUENCY = 440.0


def _tone_pcm() -> bytes:
    frame_count = int(SAMPLE_RATE * DURATION_SECONDS)
    samples = []
    for index in range(frame_count):
        sample = int(
            12000
            * math.sin(2.0 * math.pi * INPUT_FREQUENCY * index / SAMPLE_RATE)
        )
        samples.append(struct.pack("<h", sample))
    return b"".join(samples)


def _positive_zero_crossing_frequency(pcm: bytes) -> float:
    samples = [value[0] for value in struct.iter_unpack("<h", pcm)]
    crossings = sum(
        1
        for previous, current in zip(samples, samples[1:])
        if previous <= 0 < current
    )
    duration = len(samples) / SAMPLE_RATE
    return crossings / duration


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_ffmpeg_pitch_filter_preserves_duration_and_raises_frequency() -> None:
    source = _tone_pcm()
    completed = subprocess.run(
        build_ffmpeg_command(SAMPLE_RATE, 26),
        input=source,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    output = completed.stdout

    input_duration = len(source) / 2 / SAMPLE_RATE
    output_duration = len(output) / 2 / SAMPLE_RATE
    measured_frequency = _positive_zero_crossing_frequency(output)

    assert output_duration == pytest.approx(input_duration, rel=0.05)
    assert measured_frequency == pytest.approx(INPUT_FREQUENCY * 1.26, rel=0.05)
