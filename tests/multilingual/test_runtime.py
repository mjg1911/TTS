import importlib
import os
import sys
from types import SimpleNamespace

import pytest


def runtime():
    return importlib.import_module('piper.multilingual_worker.runtime')


def test_multilingual_runtime_exists():
    assert importlib.util.find_spec('piper.multilingual_worker') is not None


def test_cuda_is_required_before_loading(tmp_path):
    calls = []
    model = SimpleNamespace(from_local=lambda *a, **k: calls.append(k))
    torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False))
    with pytest.raises(RuntimeError, match='CUDA'):
        runtime().load_model(tmp_path, model_class=model, torch_module=torch)
    assert calls == []


def test_load_uses_cuda_and_explicit_v3_with_custom_reference(tmp_path):
    calls, references = [], []
    clip = tmp_path / 'reference.wav'
    clip.write_bytes(b'clip')
    loaded = SimpleNamespace(sr=24000, conds=object(), prepare_conditionals=lambda *a, **k: references.append((a, k)))
    model = SimpleNamespace(from_local=lambda *a, **k: calls.append((a, k)) or loaded)
    torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True))
    assert runtime().load_model(tmp_path, model_class=model, torch_module=torch, reference_clip=str(clip), exaggeration=0.8) is loaded
    assert calls == [((tmp_path,), {'device': 'cuda', 't3_model': 'v3'})]
    assert references == [((clip,), {'exaggeration': 0.8})]
    assert os.environ['HF_HUB_OFFLINE'] == '1'


def test_cuda_load_error_does_not_try_cpu(tmp_path):
    calls = []
    def fail(*args, **kwargs):
        calls.append(kwargs)
        raise RuntimeError('CUDA out of memory')
    torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True))
    with pytest.raises(RuntimeError, match='out of memory'):
        runtime().load_model(tmp_path, model_class=SimpleNamespace(from_local=fail), torch_module=torch)
    assert len(calls) == 1 and calls[0]['device'] == 'cuda'


def test_unicode_generation_forwards_controls_without_losing_text():
    import numpy as np
    calls = []
    def generate(text, **kwargs):
        calls.append((text, kwargs))
        return np.array([0., 0.5, -0.5], dtype=np.float32)
    model = SimpleNamespace(generate=generate)
    text = '你好世界。' * 100
    chunks = list(runtime().generate_chunks(model, text, language='zh', exaggeration=0.9, cfg_weight=0.3))
    assert ''.join(text for text, _ in calls) == text
    assert all(len(piece.encode('utf8')) <= 240 for piece, _ in calls)
    assert all(options == {'language_id': 'zh', 'exaggeration': 0.9, 'cfg_weight': 0.3} for _, options in calls)
    assert all(np.frombuffer(chunk, dtype='<i2').tolist() == [0, 16384, -16384] for chunk in chunks)


@pytest.mark.parametrize('name,value', [('language','xx'), ('exaggeration',float('nan')), ('cfg_weight',True), ('cfg_weight',1.1)])
def test_rejects_invalid_controls_before_generation(name, value):
    options = dict(language='en', exaggeration=0.5, cfg_weight=0.5)
    options[name] = value
    with pytest.raises(ValueError):
        list(runtime().generate_chunks(SimpleNamespace(), 'hello', **options))


def test_chinese_segmenter_configuration_never_downloads(monkeypatch, tmp_path):
    module = SimpleNamespace(config=SimpleNamespace(pkuseg_home='old'))
    monkeypatch.setitem(sys.modules, 'spacy_pkuseg', module)
    runtime()._configure_chinese_segmenter(tmp_path)
    assert module.config.pkuseg_home == str(tmp_path / 'pkuseg')
    with pytest.raises(RuntimeError, match='offline'):
        module.download_model('https://example.com/model.zip', str(tmp_path / 'pkuseg'), 'hash')
