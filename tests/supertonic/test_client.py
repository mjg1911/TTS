import importlib
import io
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from piper.windows_tray.worker_protocol import read_frame, write_frame


ENGINE = 'Supertonic 3'


def test_initializes_selected_cpu_worker():
    client, output = _client([
        {'type': 'hello', 'engine': ENGINE, 'protocol_version': 1},
        {'type': 'ready', 'sample_rate': 44100, 'device': 'cpu'},
    ], device='cpu')
    client.ensure_ready()
    output.seek(0)
    assert read_frame(output)['device'] == 'cpu'
    assert client.effective_device == 'cpu'
    client.shutdown()


def test_cpu_selection_rejects_gpu_readiness():
    client, _ = _client([
        {'type': 'hello', 'engine': ENGINE, 'protocol_version': 1},
        {'type': 'ready', 'sample_rate': 44100, 'device': 'cuda'},
    ], device='cpu')
    with pytest.raises(RuntimeError, match='CPU'):
        client.ensure_ready()


def _client(frames, **options):
    module = importlib.import_module('piper.windows_tray.supertonic_client')
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
    root = Path('C:/Users/test/AppData/Roaming/Piper/Supertonic3')
    installation = SimpleNamespace(
        root=root,
        model_dir=root,
        worker_executable=root / 'worker' / 'SupertonicWorker.exe',
        manifest_sha256='a' * 64,
    )
    client = module.SupertonicWorkerClient(
        installation, process_factory=lambda _: process, **options,
    )
    return client, outgoing


def test_initializes_cuda_worker_with_selected_voice_and_language():
    client, output = _client([
        {'type': 'hello', 'engine': ENGINE, 'protocol_version': 1},
        {'type': 'ready', 'sample_rate': 44100, 'device': 'cuda', 'device_message': 'Supertonic 3 uses GPU (CUDA).'},
    ], voice='F3', language='nl')

    client.ensure_ready()

    output.seek(0)
    assert read_frame(output) == {
        'type': 'initialize', 'manifest_sha256': 'a' * 64, 'device': 'cuda',
        'voice': 'F3', 'language': 'nl',
    }
    assert client.effective_device == 'cuda'
    assert client.device_message == 'Supertonic 3 uses GPU (CUDA).'
    client.shutdown()


def test_rejects_invalid_voice_and_language_at_construction():
    module = importlib.import_module('piper.windows_tray.supertonic_client')
    installation = SimpleNamespace(manifest_sha256='a' * 64)

    with pytest.raises(ValueError, match='voice'):
        module.SupertonicWorkerClient(installation, voice='default')
    with pytest.raises(ValueError, match='language'):
        module.SupertonicWorkerClient(installation, language='xx')


def test_cpu_ready_response_is_rejected():
    client, _ = _client([
        {'type': 'hello', 'engine': ENGINE, 'protocol_version': 1},
        {'type': 'ready', 'sample_rate': 44100, 'device': 'cpu'},
    ])

    with pytest.raises(RuntimeError, match='CUDA'):
        client.ensure_ready()


def test_startup_error_reaches_readiness_caller():
    client, _ = _client([
        {'type': 'hello', 'engine': ENGINE, 'protocol_version': 1},
        {'type': 'startup_error', 'message': 'CUDAExecutionProvider is unavailable.'},
    ])

    with pytest.raises(RuntimeError, match='CUDAExecutionProvider'):
        client.ensure_ready()


def _launch_fixture(module, monkeypatch, installation):
    calls, jobs = [], []
    process = SimpleNamespace(
        kill=lambda: None,
        wait=lambda **kwargs: None,
    )

    class Job:
        def assign(self, target):
            assert target is process

        def close(self):
            pass

    monkeypatch.setattr(module.subprocess, 'Popen', lambda *args, **kwargs: calls.append((args, kwargs)) or process)
    monkeypatch.setattr(module, 'WindowsKillOnCloseJob', lambda: jobs.append(Job()) or jobs[-1])
    result = module.launch_supertonic_worker(installation)
    return result, calls, jobs


def test_launch_dev_worker_sets_source_path_and_offline_mode(monkeypatch, tmp_path):
    module = importlib.import_module('piper.windows_tray.supertonic_client')
    python = tmp_path / 'python.exe'
    python.write_bytes(b'python fixture')
    monkeypatch.setenv('PIPER_SUPERTONIC_WORKER_PYTHON', str(python))
    monkeypatch.setenv('PYTHONPATH', 'existing-import-path')
    installation = SimpleNamespace(
        root=tmp_path,
        model_dir=tmp_path,
        worker_executable=tmp_path / 'worker' / 'SupertonicWorker.exe',
    )
    process, calls, jobs = _launch_fixture(module, monkeypatch, installation)

    args, kwargs = calls[0]
    assert args[0] == [str(python), '-m', 'piper.supertonic_worker.main', '--root', str(tmp_path)]
    assert kwargs['env']['PYTHONPATH'].split(module.os.pathsep) == [
        str(Path(module.__file__).resolve().parents[2]), 'existing-import-path',
    ]
    assert kwargs['env']['HF_HUB_OFFLINE'] == '1'
    assert kwargs['env']['TRANSFORMERS_OFFLINE'] == '1'
    assert process._nano_job is jobs[0]


def test_launch_packaged_worker_uses_installation_executable(monkeypatch, tmp_path):
    module = importlib.import_module('piper.windows_tray.supertonic_client')
    monkeypatch.delenv('PIPER_SUPERTONIC_WORKER_PYTHON', raising=False)
    installation = SimpleNamespace(
        root=tmp_path,
        model_dir=tmp_path,
        worker_executable=tmp_path / 'worker' / 'SupertonicWorker.exe',
    )
    _process, calls, _jobs = _launch_fixture(module, monkeypatch, installation)

    args, kwargs = calls[0]
    assert args[0] == [str(installation.worker_executable), '--root', str(tmp_path)]
    assert kwargs['env']['HF_HUB_OFFLINE'] == '1'


def test_launch_packaged_worker_prefers_current_app_bundle(monkeypatch, tmp_path):
    module = importlib.import_module('piper.windows_tray.supertonic_client')
    monkeypatch.delenv('PIPER_SUPERTONIC_WORKER_PYTHON', raising=False)
    bundled_worker = tmp_path / 'bundle' / 'supertonic_worker' / 'SupertonicWorker.exe'
    bundled_worker.parent.mkdir(parents=True)
    bundled_worker.write_bytes(b'current worker')
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path / 'bundle'), raising=False)
    installation = SimpleNamespace(
        root=tmp_path / 'model',
        model_dir=tmp_path / 'model',
        worker_executable=tmp_path / 'model' / 'worker' / 'SupertonicWorker.exe',
    )
    _process, calls, _jobs = _launch_fixture(module, monkeypatch, installation)

    args, _kwargs = calls[0]
    assert args[0] == [str(bundled_worker), '--root', str(installation.root)]

