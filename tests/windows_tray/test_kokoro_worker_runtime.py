from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys

import numpy as np

from piper.kokoro_assets import KokoroVoiceAsset
from piper.kokoro_worker.runtime import KokoroRuntime


def test_runtime_uses_explicit_local_assets_cpu_and_cached_voice(monkeypatch, tmp_path):
    config = tmp_path / "config.json"
    model = tmp_path / "kokoro-v1_0.pth"
    voice_path = tmp_path / "af_heart.pt"
    for path in (config, model, voice_path):
        path.write_bytes(b"local")
    calls = {"models": [], "loads": [], "pipelines": [], "voices": []}

    class FakeModel:
        def __init__(self, **kwargs):
            calls["models"].append(kwargs)

        def to(self, device):
            assert device == "cpu"
            return self

        def eval(self):
            return self

    class FakePipeline:
        def __init__(self, **kwargs):
            calls["pipelines"].append(kwargs)
            self.g2p = SimpleNamespace(fallback=object())

        def __call__(self, text, *, voice, speed):
            assert text == "hello"
            assert speed == 1
            calls["voices"].append(voice)
            yield "hello", "həloʊ", np.array([0.0, 0.5], dtype=np.float32)

    kokoro = ModuleType("kokoro")
    kokoro.KModel = FakeModel
    kokoro.KPipeline = FakePipeline
    torch = ModuleType("torch")
    voice_tensor = object()

    def fake_load(path, *, map_location, weights_only):
        calls["loads"].append((path, map_location, weights_only))
        return voice_tensor

    torch.load = fake_load
    spacy = ModuleType("spacy")
    spacy.cli = SimpleNamespace(download=lambda *_args, **_kwargs: None)
    monkeypatch.setitem(sys.modules, "kokoro", kokoro)
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "spacy", spacy)

    runtime = KokoroRuntime(
        config,
        model,
        {"af_heart": KokoroVoiceAsset("af_heart", voice_path, "a")},
    )
    runtime.load()
    first = list(runtime.synthesize_segments("hello", "af_heart"))
    second = list(runtime.synthesize_segments("hello", "af_heart"))
    assert calls["models"] == [{"config": str(config), "model": str(model)}]
    assert calls["loads"] == [(str(voice_path), "cpu", True)]
    assert len(calls["pipelines"]) == 1
    assert calls["pipelines"][0]["lang_code"] == "a"
    assert calls["pipelines"][0]["device"] == "cpu"
    assert calls["voices"] == [voice_tensor, voice_tensor]
    assert all(isinstance(chunk, bytes) for chunk in first + second)
