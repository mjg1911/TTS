import importlib
import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from piper.windows_tray.worker_protocol import read_frame, write_frame


ENGINE = 'Chatterbox Turbo (350M)'


def make_client(frames, **options):
    module = importlib.import_module('piper.windows_tray.turbo_client')
    incoming = io.BytesIO()
    for frame in frames:
        write_frame(incoming, frame)
    incoming.seek(0)
    outgoing = io.BytesIO()
    process = SimpleNamespace(
        stdin=outgoing,
        stdout=incoming,
        poll=lambda: None,
        terminate=lambda: None,
        wait=lambda **kwargs: None,
    )
    installation = SimpleNamespace(manifest_sha256='a' * 64)
    client = module.TurboWorkerClient(installation, process_factory=lambda _: process, **options)
    return client, outgoing


def test_initialize_sends_only_turbo_worker_fields_and_requires_cuda():
    client, output = make_client([
        {'type': 'hello', 'engine': ENGINE, 'protocol_version': 1},
        {'type': 'ready', 'sample_rate': 24000, 'device': 'cuda'},
    ])

    client.ensure_ready()

    output.seek(0)
    assert read_frame(output) == {
        'type': 'initialize', 'manifest_sha256': 'a' * 64, 'device': 'cuda',
    }
    assert client.effective_device == 'cuda'
    client.shutdown()


def test_custom_reference_is_the_only_optional_initialization_field():
    client, output = make_client([
        {'type': 'hello', 'engine': ENGINE, 'protocol_version': 1},
        {'type': 'ready', 'sample_rate': 24000, 'device': 'cuda'},
    ], reference_clip='C:/voices/custom.wav')

    client.ensure_ready()

    output.seek(0)
    assert read_frame(output) == {
        'type': 'initialize', 'manifest_sha256': 'a' * 64, 'device': 'cuda',
        'reference_clip': str(Path('C:/voices/custom.wav').resolve()),
    }
    client.shutdown()


@pytest.mark.parametrize('retired_option,value', [
    ('language', 'nl'), ('exaggeration', 0.8), ('cfg_weight', 0.3),
])
def test_client_rejects_retired_multilingual_options(retired_option, value):
    module = importlib.import_module('piper.windows_tray.turbo_client')
    with pytest.raises(TypeError):
        module.TurboWorkerClient(SimpleNamespace(manifest_sha256='a' * 64), **{retired_option: value})


def test_cpu_ready_response_is_rejected():
    client, _ = make_client([
        {'type': 'hello', 'engine': ENGINE, 'protocol_version': 1},
        {'type': 'ready', 'sample_rate': 24000, 'device': 'cpu'},
    ])
    with pytest.raises(RuntimeError, match='CUDA'):
        client.ensure_ready()


def test_worker_gpu_error_reaches_readiness_caller():
    client, _ = make_client([
        {'type': 'hello', 'engine': ENGINE, 'protocol_version': 1},
        {'type': 'startup_error', 'message': 'NVIDIA GPU with CUDA is required.'},
    ])
    with pytest.raises(RuntimeError, match='NVIDIA GPU'):
        client.ensure_ready()


def test_nano_worker_handshake_is_rejected():
    client, _ = make_client([{'type': 'hello', 'engine': 'Chatterbox Nano', 'protocol_version': 1}])
    with pytest.raises(RuntimeError, match='handshake'):
        client.ensure_ready()


def test_launch_uses_turbo_worker_environment_and_module(monkeypatch):
    module = importlib.import_module('piper.windows_tray.turbo_client')
    calls = []
    process = object()
    monkeypatch.setattr(module, 'launch_nano_worker', lambda installation, **options: calls.append((installation, options)) or process)
    installation = SimpleNamespace(root='C:/Piper/ChatterboxTurbo', worker_executable='TurboWorker.exe')

    assert module.launch_turbo_worker(installation) is process
    assert calls == [(installation, {
        'python_env': 'PIPER_TURBO_WORKER_PYTHON', 'module': 'piper.turbo_worker.main',
    })]
