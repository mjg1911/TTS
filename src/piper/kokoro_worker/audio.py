from __future__ import annotations

import numpy as np


def float_audio_to_pcm16(audio: np.ndarray) -> bytes:
    values = np.asarray(audio, dtype=np.float32)
    if values.ndim != 1:
        raise ValueError("Kokoro audio must be mono")
    clipped = np.clip(values, -1.0, 1.0)
    scaled = np.where(clipped >= 0, clipped * 32767.0, clipped * 32768.0)
    return np.rint(scaled).astype("<i2").tobytes()
