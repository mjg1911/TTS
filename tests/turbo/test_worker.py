import importlib
import io
from types import SimpleNamespace

from piper.windows_tray.worker_protocol import decode_audio, read_frame, write_frame


ENGINE = 'Chatterbox Turbo (350M)'


def _worker(monkeypatch, tmp_path, load_model):
    module = importlib.import_module('piper.turbo_worker.main')
    monkeypatch.setattr(module, 'inspect_turbo_installation', lambda _: SimpleNamespace(
        root=tmp_path, model_dir=tmp_path, manifest_sha256='a' * 64,
    ))
    monkeypatch.setattr(module, '_configure_numba_cache', lambda _: None)
    monkeypatch.setattr(module, 'load_model', load_model)
    return module


def test_worker_reports_cuda_startup_failure(monkeypatch, tmp_path):
    def unavailable(*args, **kwargs):
        raise RuntimeError('NVIDIA GPU with CUDA is required.')

    module = _worker(monkeypatch, tmp_path, unavailable)
    incoming, outgoing = io.BytesIO(), io.BytesIO()
    write_frame(incoming, {
        'type': 'initialize', 'manifest_sha256': 'a' * 64, 'device': 'cuda',
    })
    incoming.seek(0)

    module.serve(tmp_path, incoming, outgoing)

    outgoing.seek(0)
    assert read_frame(outgoing) == {'type': 'hello', 'engine': ENGINE, 'protocol_version': 1}
    assert read_frame(outgoing) == {
        'type': 'startup_error', 'message': 'NVIDIA GPU with CUDA is required.',
    }


def test_worker_rejects_retired_options_before_model_loading(monkeypatch, tmp_path):
    loads = []
    module = _worker(monkeypatch, tmp_path, lambda *args, **kwargs: loads.append((args, kwargs)))
    incoming, outgoing = io.BytesIO(), io.BytesIO()
    write_frame(incoming, {
        'type': 'initialize', 'manifest_sha256': 'a' * 64, 'device': 'cuda',
        'language': 'en', 'exaggeration': 0.5, 'cfg_weight': 0.5,
    })
    incoming.seek(0)

    module.serve(tmp_path, incoming, outgoing)

    outgoing.seek(0)
    read_frame(outgoing)
    error = read_frame(outgoing)
    assert error['type'] == 'startup_error'
    assert loads == []


def test_worker_passes_only_optional_reference_to_runtime(monkeypatch, tmp_path):
    loaded, calls = SimpleNamespace(sr=24000), []

    def load(directory, *, reference_clip=None):
        calls.append((directory, reference_clip))
        return loaded

    module = _worker(monkeypatch, tmp_path, load)
    incoming, outgoing = io.BytesIO(), io.BytesIO()
    write_frame(incoming, {
        'type': 'initialize', 'manifest_sha256': 'a' * 64, 'device': 'cuda',
        'reference_clip': 'C:/voices/custom.wav',
    })
    write_frame(incoming, {'type': 'shutdown'})
    incoming.seek(0)

    module.serve(tmp_path, incoming, outgoing)

    outgoing.seek(0)
    assert read_frame(outgoing) == {'type': 'hello', 'engine': ENGINE, 'protocol_version': 1}
    assert read_frame(outgoing) == {
        'type': 'ready', 'sample_rate': 24000, 'device': 'cuda',
        'device_message': 'Chatterbox Turbo (350M) uses GPU (CUDA).',
    }
    assert calls == [(tmp_path, 'C:/voices/custom.wav')]


def test_worker_generates_framed_audio_without_language_or_style_arguments(monkeypatch, tmp_path):
    generated = []
    model = SimpleNamespace(sr=24000)
    module = _worker(monkeypatch, tmp_path, lambda *args, **kwargs: model)

    def chunks(received_model, text):
        generated.append((received_model, text))
        yield b'\x01\x00\x02\x00'

    monkeypatch.setattr(module, 'generate_chunks', chunks)
    incoming, outgoing = io.BytesIO(), io.BytesIO()
    write_frame(incoming, {'type': 'initialize', 'manifest_sha256': 'a' * 64, 'device': 'cuda'})
    write_frame(incoming, {
        'type': 'synthesize', 'request_id': 4, 'text': 'Speak this clearly.', 'voice_id': 'default',
    })
    write_frame(incoming, {'type': 'shutdown'})
    incoming.seek(0)

    module.serve(tmp_path, incoming, outgoing)

    outgoing.seek(0)
    read_frame(outgoing)
    read_frame(outgoing)
    audio_frame = read_frame(outgoing)
    assert audio_frame['type'] == 'audio'
    assert audio_frame['request_id'] == 4
    assert decode_audio(audio_frame['audio']) == b'\x01\x00\x02\x00'
    assert read_frame(outgoing) == {'type': 'response_end', 'request_id': 4}
    assert generated == [(model, 'Speak this clearly.')]
