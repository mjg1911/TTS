import os
from pathlib import Path

import pytest

from piper.kokoro_assets import verify_kokoro_installation
from piper.kokoro_worker.runtime import KokoroRuntime


@pytest.mark.skipif(
    "PIPER_KOKORO_TEST_ROOT" not in os.environ,
    reason="real Kokoro payload not configured",
)
def test_real_kokoro_default_voice_synthesizes_offline():
    installation = verify_kokoro_installation(Path(os.environ["PIPER_KOKORO_TEST_ROOT"]))
    runtime = KokoroRuntime(installation.config_path, installation.model_path, installation.voices)
    runtime.load()
    chunks = list(runtime.synthesize_segments("Offline Kokoro smoke test.", "af_heart"))
    assert chunks
    assert all(isinstance(chunk, bytes) and len(chunk) % 2 == 0 for chunk in chunks)
