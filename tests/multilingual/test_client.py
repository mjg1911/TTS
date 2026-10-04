import importlib
import io
from types import SimpleNamespace

import pytest
from piper.windows_tray.worker_protocol import write_frame, read_frame

ENGINE = 'Chatterbox Multilingual V3 (500M)'


def make_client(frames, **options):
    module = importlib.import_module('piper.windows_tray.multilingual_client')
    incoming = io.BytesIO()
    for frame in frames:
        write_frame(incoming, frame)
    incoming.seek(0)
    outgoing = io.BytesIO()
    process = SimpleNamespace(stdin=outgoing, stdout=incoming, poll=lambda: None, terminate=lambda: None, wait=lambda **kwargs: None)
    installation = SimpleNamespace(manifest_sha256='a' * 64)
    client = module.MultilingualWorkerClient(installation, process_factory=lambda _: process, **options)
    return client, outgoing


def test_initialize_forwards_settings_and_requires_cuda():
    client, output = make_client([
        {'type':'hello','engine':ENGINE,'protocol_version':1},
        {'type':'ready','sample_rate':24000,'device':'cuda'},
    ], language='nl', exaggeration=0.8, cfg_weight=0.3)
    client.ensure_ready()
    output.seek(0)
    request = read_frame(output)
    assert request == {'type':'initialize','manifest_sha256':'a'*64,'device':'cuda','language':'nl','exaggeration':0.8,'cfg_weight':0.3}
    assert client.effective_device == 'cuda'
    client.shutdown()


def test_cpu_ready_response_is_rejected():
    client, _ = make_client([
        {'type':'hello','engine':ENGINE,'protocol_version':1},
        {'type':'ready','sample_rate':24000,'device':'cpu'},
    ])
    with pytest.raises(RuntimeError, match='CUDA'):
        client.ensure_ready()


def test_worker_gpu_error_reaches_readiness_caller():
    client, _ = make_client([
        {'type':'hello','engine':ENGINE,'protocol_version':1},
        {'type':'startup_error','message':'NVIDIA GPU with CUDA is required.'},
    ])
    with pytest.raises(RuntimeError, match='NVIDIA GPU'):
        client.ensure_ready()


def test_nano_worker_handshake_is_rejected():
    client, _ = make_client([{'type':'hello','engine':'Chatterbox Nano','protocol_version':1}])
    with pytest.raises(RuntimeError, match='handshake'):
        client.ensure_ready()
