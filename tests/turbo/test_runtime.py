from contextlib import nullcontext
import importlib
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest


def runtime():
    return importlib.import_module('piper.turbo_worker.runtime')


def test_turbo_runtime_package_exists():
    assert importlib.util.find_spec('piper.turbo_worker') is not None


def test_cuda_is_required_before_local_model_loading(tmp_path):
    calls = []
    model_class = SimpleNamespace(from_local=lambda *args, **kwargs: calls.append((args, kwargs)))
    torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False))

    with pytest.raises(RuntimeError, match='CUDA'):
        runtime().load_model(tmp_path, model_class=model_class, torch_module=torch)

    assert calls == []


def test_load_uses_pinned_turbo_checkpoint_and_custom_reference(tmp_path):
    calls, references = [], []
    clip = tmp_path / 'reference.wav'
    clip.write_bytes(b'wav fixture')
    loaded = SimpleNamespace(
        sr=24000,
        conds=object(),
        prepare_conditionals=lambda *args, **kwargs: references.append((args, kwargs)),
    )
    model_class = SimpleNamespace(from_local=lambda *args, **kwargs: calls.append((args, kwargs)) or loaded)
    torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True))

    assert runtime().load_model(
        tmp_path, model_class=model_class, torch_module=torch, reference_clip=str(clip)
    ) is loaded

    assert calls == [((tmp_path,), {'device': 'cuda', 'nano': False})]
    assert references == [((clip,), {})]
    assert loaded.effective_device == 'cuda'
    assert os.environ['HF_HUB_OFFLINE'] == '1'
    assert os.environ['TRANSFORMERS_OFFLINE'] == '1'


@pytest.mark.parametrize('reference', ['relative.wav', 'missing.wav', 'reference.mp3'])
def test_rejects_invalid_reference_before_loading(tmp_path, reference):
    calls = []
    model_class = SimpleNamespace(from_local=lambda *args, **kwargs: calls.append((args, kwargs)))
    torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True))

    with pytest.raises(ValueError, match='absolute WAV file'):
        runtime().load_model(tmp_path, model_class=model_class, torch_module=torch, reference_clip=reference)

    assert calls == []


def test_cuda_load_failure_does_not_retry_on_cpu(tmp_path):
    calls = []

    def fail(*args, **kwargs):
        calls.append((args, kwargs))
        raise RuntimeError('CUDA out of memory')

    torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True))
    with pytest.raises(RuntimeError, match='out of memory'):
        runtime().load_model(tmp_path, model_class=SimpleNamespace(from_local=fail), torch_module=torch)

    assert calls == [((tmp_path,), {'device': 'cuda', 'nano': False})]


def test_generation_uses_turbo_defaults_and_keeps_audio_chunking():
    calls = []

    def generate(text, *args, **kwargs):
        calls.append((text, args, kwargs))
        return np.full(40000, 0.25, dtype=np.float32)

    model = SimpleNamespace(generate=generate)
    text = ('A sentence, with enough words. ' * 40).strip()

    torch = SimpleNamespace(inference_mode=nullcontext)
    chunks = list(runtime().generate_chunks(model, text, torch_module=torch))

    assert ' '.join(piece for piece, _, _ in calls) == text
    assert all(len(piece.encode('utf-8')) <= 240 for piece, _, _ in calls)
    assert all(args == () and kwargs == {} for _, args, kwargs in calls)
    assert len(chunks) == len(calls) * 2
    assert all(len(chunk) <= 65536 for chunk in chunks)
    assert all(np.frombuffer(chunk, dtype='<i2').tolist() == [8192] * (len(chunk) // 2) for chunk in chunks)
