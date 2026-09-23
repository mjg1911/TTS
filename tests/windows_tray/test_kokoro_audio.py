import numpy as np

from piper.kokoro_worker.audio import float_audio_to_pcm16


def test_float_audio_to_pcm16_clips_and_uses_little_endian():
    audio = np.array([-2.0, -1.0, 0.0, 0.5, 1.0, 2.0], dtype=np.float32)
    samples = np.frombuffer(float_audio_to_pcm16(audio), dtype="<i2")
    assert samples.tolist() == [-32768, -32768, 0, 16384, 32767, 32767]


def test_float_audio_to_pcm16_requires_one_dimension():
    try:
        float_audio_to_pcm16(np.zeros((2, 2), dtype=np.float32))
    except ValueError as error:
        assert "mono" in str(error)
    else:
        raise AssertionError("expected mono validation failure")
