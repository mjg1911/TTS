import importlib
import io
import pytest
from types import SimpleNamespace

from piper.windows_tray.worker_protocol import decode_audio, read_frame, write_frame


ENGINE = 'Supertonic 3'


def _worker(monkeypatch, tmp_path, load_model):
    module = importlib.import_module('piper.supertonic_worker.main')
    monkeypatch.setattr(module, 'inspect_supertonic3_installation', lambda _: SimpleNamespace(
        root=tmp_path, model_dir=tmp_path, manifest_sha256='a' * 64,
    ))
    monkeypatch.setattr(module, 'load_model', load_model)
    return module


def test_worker_reports_cuda_startup_failure(monkeypatch, tmp_path):
    def unavailable(*args, **kwargs):
        raise RuntimeError('CUDAExecutionProvider is unavailable.')

    module = _worker(monkeypatch, tmp_path, unavailable)
    incoming, outgoing = io.BytesIO(), io.BytesIO()
    write_frame(incoming, {
        'type': 'initialize', 'manifest_sha256': 'a' * 64, 'device': 'cuda',
        'voice': 'M1', 'language': 'en',
    })
    incoming.seek(0)

    module.serve(tmp_path, incoming, outgoing)

    outgoing.seek(0)
    assert read_frame(outgoing) == {'type': 'hello', 'engine': ENGINE, 'protocol_version': 1}
    assert read_frame(outgoing) == {
        'type': 'startup_error', 'message': 'CUDAExecutionProvider is unavailable.',
    }


def test_worker_rejects_invalid_device_before_model_loading(monkeypatch, tmp_path):
    loads = []
    module = _worker(monkeypatch, tmp_path, lambda *args, **kwargs: loads.append((args, kwargs)))
    incoming, outgoing = io.BytesIO(), io.BytesIO()
    write_frame(incoming, {
        'type': 'initialize', 'manifest_sha256': 'a' * 64, 'device': 'auto',
        'voice': 'M1', 'language': 'en',
    })
    incoming.seek(0)

    module.serve(tmp_path, incoming, outgoing)

    outgoing.seek(0)
    read_frame(outgoing)
    assert read_frame(outgoing)['type'] == 'startup_error'
    assert loads == []


@pytest.mark.parametrize("device", ["cpu", "cuda"])
def test_worker_loads_requested_style_and_returns_framed_pcm(monkeypatch, tmp_path, device):
    loaded = SimpleNamespace(sample_rate=44100, voice_style=object(), language='nl')
    loads = []

    def load(directory, *, voice, language, device):
        loads.append((directory, voice, language, device))
        loaded.language = language
        return loaded

    module = _worker(monkeypatch, tmp_path, load)
    generated = []

    def chunks(model, text):
        generated.append((model, text))
        yield b'\x01\x00\x02\x00'

    monkeypatch.setattr(module, 'generate_chunks', chunks)
    incoming, outgoing = io.BytesIO(), io.BytesIO()
    write_frame(incoming, {
        'type': 'initialize', 'manifest_sha256': 'a' * 64, 'device': device,
        'voice': 'F4', 'language': 'nl',
    })
    write_frame(incoming, {
        'type': 'synthesize', 'request_id': 7, 'text': 'Spreek dit uit.', 'voice_id': 'default',
    })
    write_frame(incoming, {'type': 'shutdown'})
    incoming.seek(0)

    module.serve(tmp_path, incoming, outgoing)

    outgoing.seek(0)
    assert read_frame(outgoing) == {'type': 'hello', 'engine': ENGINE, 'protocol_version': 1}
    assert read_frame(outgoing) == {
        'type': 'ready', 'sample_rate': 44100, 'device': device,
        'device_message': 'Supertonic 3 uses GPU (CUDA).' if device == 'cuda' else 'Supertonic 3 uses CPU.',
    }
    audio = read_frame(outgoing)
    assert audio['type'] == 'audio' and audio['request_id'] == 7
    assert decode_audio(audio['audio']) == b'\x01\x00\x02\x00'
    assert read_frame(outgoing) == {'type': 'response_end', 'request_id': 7}
    assert loads == [(tmp_path, 'F4', 'nl', device)]
    assert generated == [(loaded, 'Spreek dit uit.')]

