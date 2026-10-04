"""Nano contracts; no model weights or inference dependencies required."""
import hashlib
import importlib
import io
import json
from pathlib import Path
from threading import Event
from types import SimpleNamespace
import pytest


def modules():
    return (importlib.import_module('piper.nano_assets'), importlib.import_module('piper.nano_worker.runtime'), importlib.import_module('piper.windows_tray.nano_client'))


@pytest.fixture
def fake_model_hashes(monkeypatch):
    assets, _, _ = modules()
    pinned_hashes = getattr(assets, 'MODEL_FILE_SHA256', None)
    asset_hash = hashlib.sha256(b'asset').hexdigest()
    monkeypatch.setattr(assets, 'MODEL_FILE_SHA256', {name: asset_hash for name in assets.REQUIRED_MODEL_FILES}, raising=False)
    return pinned_hashes


def installation(tmp_path):
    assets, _, _ = modules()
    names = ['worker/NanoWorker.exe', *['model/' + name for name in assets.REQUIRED_MODEL_FILES]]
    files = {}
    for name in names:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'asset')
        files[name] = hashlib.sha256(b'asset').hexdigest()
    (tmp_path / 'manifest.json').write_text(json.dumps({'manifest_version': 1, 'engine': 'Chatterbox Nano', 'source_revision': assets.SOURCE_REVISION, 'model_revision': assets.MODEL_REVISION, 'files': files}))
    return assets.inspect_nano_installation(tmp_path)


def test_modules_exist():
    for name in ('piper.nano_assets', 'piper.nano_worker.runtime', 'piper.windows_tray.nano_client'):
        assert importlib.util.find_spec(name) is not None


@pytest.mark.usefixtures('fake_model_hashes')
def test_manifest_verifies_integrity_and_coverage(tmp_path):
    item = installation(tmp_path)
    assert item.worker_executable == tmp_path / 'worker/NanoWorker.exe'
    assert item.model_dir == tmp_path / 'model'
    item.worker_executable.write_bytes(b'tampered')
    with pytest.raises(ValueError, match='hash'):
        modules()[0].inspect_nano_installation(tmp_path)


@pytest.mark.usefixtures('fake_model_hashes')
def test_manifest_rejects_unhashed_files_and_escape(tmp_path):
    installation(tmp_path)
    (tmp_path / 'extra.dll').write_bytes(b'extra')
    with pytest.raises(ValueError, match='inventory'):
        modules()[0].inspect_nano_installation(tmp_path)
    (tmp_path / 'extra.dll').unlink()
    manifest = json.loads((tmp_path / 'manifest.json').read_text())
    manifest['files']['../escape'] = '0' * 64
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='escapes'):
        modules()[0].inspect_nano_installation(tmp_path)


def test_sentence_chunking_preserves_tags_and_bounds():
    _, runtime, _ = modules()
    text = 'Hello [laugh]. ' + ('Longword ' * 100) + 'x' * 400
    chunks = list(runtime.split_text(text))
    assert all(len(chunk.encode('utf8')) <= 240 for chunk in chunks)
    assert ''.join(''.join(chunks).split()) == ''.join(text.split())
    assert '[laugh]' in chunks[0]


def test_pcm_conversion_clips_and_rejects_nonfinite():
    import numpy as np
    _, runtime, _ = modules()
    output = runtime.pcm16(np.array([[-2., 0., 2.]], dtype=np.float32))
    assert np.frombuffer(output, dtype='<i2').tolist() == [-32768, 0, 32767]
    with pytest.raises(ValueError, match='finite'):
        runtime.pcm16(np.array([float('nan')]))


def test_model_load_uses_local_cpu_nano_and_requires_default_voice(tmp_path):
    _, runtime, _ = modules()
    calls = []
    class Model:
        @classmethod
        def from_local(cls, directory, **kwargs):
            calls.append((directory, kwargs))
            return SimpleNamespace(sr=22050, conds=object())
    loaded = runtime.load_model(tmp_path, model_class=Model)
    assert loaded.sr == 22050
    assert calls == [(tmp_path, {'device': 'cpu', 'nano': True})]


def test_model_load_requests_cuda_for_nano_when_selected(tmp_path, monkeypatch):
    _, runtime, _ = modules()
    calls = []
    class Torch:
        class cuda:
            @staticmethod
            def is_available():
                return True
    class Model:
        @classmethod
        def from_local(cls, directory, **kwargs):
            calls.append((directory, kwargs))
            return SimpleNamespace(sr=22050, conds=object())
    monkeypatch.setitem(__import__('sys').modules, 'torch', Torch())
    loaded = runtime.load_model(tmp_path, model_class=Model, device='cuda')
    assert loaded.sr == 22050
    assert calls == [(tmp_path, {'device': 'cuda', 'nano': True})]


def test_cuda_request_falls_back_to_cpu_with_message(tmp_path, monkeypatch):
    _, runtime, _ = modules()
    calls = []
    class Torch:
        class cuda:
            @staticmethod
            def is_available():
                return False
    class Model:
        @classmethod
        def from_local(cls, directory, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(sr=22050, conds=object())
    monkeypatch.setitem(__import__('sys').modules, 'torch', Torch())
    loaded = runtime.load_model(tmp_path, model_class=Model, device='cuda')
    assert calls == [{'device': 'cpu', 'nano': True}]
    assert loaded.effective_device == 'cpu'
    assert loaded.device_message == 'CUDA unavailable; using CPU.'


class Process:
    def __init__(self, frames):
        from piper.windows_tray.worker_protocol import write_frame
        self.stdout = io.BytesIO()
        for frame in frames:
            write_frame(self.stdout, frame)
        self.stdout.seek(0)
        self.stdin = io.BytesIO()
        self.killed = False
    def poll(self): return 0 if self.killed else None
    def terminate(self): self.killed = True
    def kill(self): self.killed = True
    def wait(self, timeout=None): return 0


def test_nano_worker_launch_hides_console_and_assigns_kill_on_close_job(
    tmp_path, monkeypatch
):
    import os
    import subprocess

    _, _, client = modules()
    worker_executable = tmp_path / "NanoWorker.exe"
    process = SimpleNamespace(_handle=123)
    calls = {}

    class FakeJob:
        def assign(self, candidate):
            calls["assigned"] = candidate

    job = FakeJob()

    def fake_popen(argv, **kwargs):
        calls["argv"] = argv
        calls["kwargs"] = kwargs
        return process

    monkeypatch.setattr(
        client,
        "os",
        SimpleNamespace(name="nt", environ=os.environ),
    )
    monkeypatch.setattr(client.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(client, "WindowsKillOnCloseJob", lambda: job)

    launched = client.launch_nano_worker(
        SimpleNamespace(root=tmp_path, worker_executable=worker_executable)
    )

    assert launched is process
    assert calls["argv"] == [str(worker_executable), "--root", str(tmp_path)]
    assert calls["kwargs"]["stdin"] is subprocess.PIPE
    assert calls["kwargs"]["stdout"] is subprocess.PIPE
    assert calls["kwargs"]["stderr"] is subprocess.DEVNULL
    assert calls["kwargs"]["creationflags"] & client.CREATE_NO_WINDOW
    assert calls["kwargs"]["env"]["HF_HUB_OFFLINE"] == "1"
    assert calls["kwargs"]["env"]["TRANSFORMERS_OFFLINE"] == "1"
    assert calls["assigned"] is process
    assert process._nano_job is job


def test_nano_worker_launch_failure_uses_bounded_cleanup_and_preserves_error(
    tmp_path, monkeypatch
):
    import os
    import subprocess

    _, _, client = modules()
    calls = []

    class Process:
        _handle = 123

        def kill(self):
            calls.append("kill")

        def wait(self, timeout=None):
            calls.append(("wait", timeout))
            raise subprocess.TimeoutExpired("nano worker", timeout)

    class FailingJob:
        def assign(self, _process):
            calls.append("assign")
            raise OSError("job assignment failed")

        def close(self):
            calls.append("close")

    process = Process()
    monkeypatch.setattr(
        client,
        "os",
        SimpleNamespace(name="nt", environ=os.environ),
    )
    monkeypatch.setattr(client.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(client, "WindowsKillOnCloseJob", FailingJob)

    with pytest.raises(OSError, match="job assignment failed"):
        client.launch_nano_worker(
            SimpleNamespace(root=tmp_path, worker_executable=tmp_path / "NanoWorker.exe")
        )

    assert calls == ["assign", "kill", ("wait", 1), "close"]


@pytest.mark.usefixtures('fake_model_hashes')
def test_client_dynamic_rate_and_pcm(tmp_path):
    from piper.windows_tray.worker_protocol import encode_audio
    _, _, client = modules()
    process = Process([{'type':'hello','engine':'Chatterbox Nano','protocol_version':1}, {'type':'ready','sample_rate':22050}, {'type':'audio','request_id':1,'audio':encode_audio(b'\0\0')}, {'type':'response_end','request_id':1}])
    worker = client.NanoWorkerClient(installation(tmp_path), process_factory=lambda _: process)
    result = worker.synthesize('Hello', Event())
    assert result.sample_rate == 22050
    assert list(result.chunks) == [b'\0\0']
    worker.shutdown()
    assert process.killed


@pytest.mark.usefixtures('fake_model_hashes')
def test_client_sends_device_and_exposes_effective_device_message(tmp_path):
    _, _, client = modules()
    process = Process([
        {'type':'hello','engine':'Chatterbox Nano','protocol_version':1},
        {'type':'ready','sample_rate':22050,'device':'cpu','device_message':'CUDA unavailable; using CPU.'},
    ])
    worker = client.NanoWorkerClient(installation(tmp_path), process_factory=lambda _: process, device='cuda')
    worker.ensure_ready()
    assert worker.device == 'cuda'
    assert worker.effective_device == 'cpu'
    assert worker.device_message == 'CUDA unavailable; using CPU.'
    process.stdin.seek(0)
    from piper.windows_tray.worker_protocol import read_frame
    assert read_frame(process.stdin) == {
        'type': 'initialize',
        'manifest_sha256': worker.installation.manifest_sha256,
        'device': 'cuda',
    }
    worker.shutdown()


@pytest.mark.usefixtures('fake_model_hashes')
def test_cpu_client_initialization_is_accepted_by_legacy_worker(tmp_path):
    from piper.windows_tray.worker_protocol import read_frame, validate_initialize
    _, _, client = modules()
    process = Process([
        {'type':'hello','engine':'Chatterbox Nano','protocol_version':1},
        {'type':'ready','sample_rate':22050},
    ])
    worker = client.NanoWorkerClient(installation(tmp_path), process_factory=lambda _: process)
    try:
        worker.ensure_ready()
        process.stdin.seek(0)
        validate_initialize(read_frame(process.stdin))
        assert worker.effective_device == 'cpu'
    finally:
        worker.shutdown()


@pytest.mark.usefixtures('fake_model_hashes')
def test_client_treats_legacy_ready_without_device_as_cpu_fallback(tmp_path):
    _, _, client = modules()
    process = Process([
        {'type':'hello','engine':'Chatterbox Nano','protocol_version':1},
        {'type':'ready','sample_rate':22050},
    ])
    worker = client.NanoWorkerClient(installation(tmp_path), process_factory=lambda _: process, device='cuda')
    worker.ensure_ready()
    assert worker.effective_device == 'cpu'
    assert worker.device_message == 'CUDA unavailable; using CPU.'
    worker.shutdown()


@pytest.mark.usefixtures('fake_model_hashes')
def test_cancel_before_sending_keeps_loaded_worker(tmp_path):
    _, _, client = modules()
    processes = []
    def factory(_):
        item = Process([{'type':'hello','engine':'Chatterbox Nano','protocol_version':1}, {'type':'ready','sample_rate':24000}])
        processes.append(item)
        return item
    worker = client.NanoWorkerClient(installation(tmp_path), process_factory=factory)
    cancel = Event()
    result = worker.synthesize('Hello', cancel)
    cancel.set()
    assert list(result.chunks) == []
    assert not processes[0].killed
    worker.ensure_ready()
    assert len(processes) == 1
    worker.shutdown()


@pytest.mark.usefixtures('fake_model_hashes')
@pytest.mark.parametrize('close_iterator', [False, True])
def test_cancel_discards_remaining_audio_and_reuses_worker(tmp_path, close_iterator):
    from piper.windows_tray.worker_protocol import encode_audio
    _, _, client = modules()
    process = Process([
        {'type': 'hello', 'engine': 'Chatterbox Nano', 'protocol_version': 1},
        {'type': 'ready', 'sample_rate': 24000},
        {'type': 'audio', 'request_id': 1, 'audio': encode_audio(b'\0\0')},
        *[{'type': 'audio', 'request_id': 1, 'audio': encode_audio(b'\1\0')} for _ in range(20)],
        {'type': 'response_end', 'request_id': 1},
        {'type': 'audio', 'request_id': 2, 'audio': encode_audio(b'\2\0')},
        {'type': 'response_end', 'request_id': 2},
    ])
    launches = []
    def factory(_):
        launches.append(True)
        return process
    worker = client.NanoWorkerClient(installation(tmp_path), process_factory=factory)
    try:
        cancel = Event()
        chunks = worker.synthesize('Old sentence', cancel).chunks
        assert next(chunks) == b'\0\0'
        cancel.set()
        if close_iterator:
            chunks.close()
        else:
            assert list(chunks) == []
        assert list(worker.synthesize('New sentence', Event()).chunks) == [b'\2\0']
        assert launches == [True]
        assert not process.killed
    finally:
        worker.shutdown()


@pytest.mark.usefixtures('fake_model_hashes')
def test_cancel_next_request_while_draining_keeps_model_ready(tmp_path):
    import os
    import threading
    from piper.windows_tray.worker_protocol import write_frame, encode_audio
    _, _, client = modules()
    process = Process([])
    reader, writer = os.pipe()
    process.stdout = os.fdopen(reader, 'rb', buffering=0)
    pipe = os.fdopen(writer, 'wb', buffering=0)
    original_terminate = process.terminate
    def terminate():
        original_terminate()
        pipe.close()
    process.terminate = terminate
    launches = []
    def factory(_):
        launches.append(True)
        return process
    for frame in (
        {'type': 'hello', 'engine': 'Chatterbox Nano', 'protocol_version': 1},
        {'type': 'ready', 'sample_rate': 24000},
        {'type': 'audio', 'request_id': 1, 'audio': encode_audio(b'\0\0')},
    ):
        write_frame(pipe, frame)
    worker = client.NanoWorkerClient(installation(tmp_path), process_factory=factory)
    thread = None
    try:
        chunks = worker.synthesize('Old sentence', Event()).chunks
        assert next(chunks) == b'\0\0'
        chunks.close()
        next_cancel = Event()
        waiting = Event()
        finished = Event()
        errors = []
        def next_request():
            waiting.set()
            try:
                worker.synthesize('Cancelled while waiting', next_cancel)
            except client.NanoUnavailable as error:
                errors.append(str(error))
            finally:
                finished.set()
        thread = threading.Thread(target=next_request)
        thread.start()
        assert waiting.wait(1)
        assert not finished.wait(0.1)
        next_cancel.set()
        assert finished.wait(1)
        assert errors == ['Nano request cancelled']
        assert not process.killed
        write_frame(pipe, {'type': 'response_end', 'request_id': 1})
        worker.ensure_ready()
        write_frame(pipe, {'type': 'audio', 'request_id': 2, 'audio': encode_audio(b'\2\0')})
        write_frame(pipe, {'type': 'response_end', 'request_id': 2})
        assert list(worker.synthesize('New sentence', Event()).chunks) == [b'\2\0']
        assert launches == [True]
    finally:
        worker.shutdown()
        pipe.close()
        if thread is not None:
            thread.join(1)


@pytest.mark.usefixtures('fake_model_hashes')
def test_invalid_cancelled_response_discards_unusable_worker(tmp_path):
    from piper.windows_tray.worker_protocol import encode_audio
    _, _, client = modules()
    process = Process([
        {'type': 'hello', 'engine': 'Chatterbox Nano', 'protocol_version': 1},
        {'type': 'ready', 'sample_rate': 24000},
        {'type': 'audio', 'request_id': 1, 'audio': encode_audio(b'\0\0')},
        {'type': 'response_end', 'request_id': 999},
    ])
    worker = client.NanoWorkerClient(installation(tmp_path), process_factory=lambda _: process)
    try:
        chunks = worker.synthesize('Old sentence', Event()).chunks
        assert next(chunks) == b'\0\0'
        chunks.close()
        assert worker._drain_done.wait(1)
        assert process.killed
    finally:
        worker.shutdown()


@pytest.mark.usefixtures('fake_model_hashes')
def test_speech_stop_then_new_message_reuses_nano_without_stale_audio(tmp_path):
    from piper.windows_tray.speech import SpeechWorker, SpeechRequest, SpeechEventKind
    from piper.windows_tray.worker_protocol import encode_audio, read_frame
    _, _, client = modules()
    process = Process([
        {'type': 'hello', 'engine': 'Chatterbox Nano', 'protocol_version': 1},
        {'type': 'ready', 'sample_rate': 24000},
        {'type': 'audio', 'request_id': 1, 'audio': encode_audio(b'\0\0')},
        {'type': 'audio', 'request_id': 1, 'audio': encode_audio(b'\1\0')},
        {'type': 'response_end', 'request_id': 1},
        {'type': 'audio', 'request_id': 2, 'audio': encode_audio(b'\2\0')},
        {'type': 'response_end', 'request_id': 2},
    ])
    launches = []
    def factory(_):
        launches.append(True)
        return process
    backend = client.NanoWorkerClient(installation(tmp_path), process_factory=factory)
    finished = Event()
    events = []
    played = []
    def on_event(event):
        events.append(event)
        if event.generation == 2 and event.kind is not SpeechEventKind.STARTED:
            finished.set()
    class Player:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def stop(self): pass
        def play(self, audio):
            played.append(audio)
            if audio == b'\0\0':
                speech.cancel_active(1)
                speech.submit(SpeechRequest(2, 'New message.'))
    speech = SpeechWorker(lambda: backend, on_event, player_factory=lambda rate: Player())
    try:
        speech.submit(SpeechRequest(1, 'Old sentence. Never generate this sentence.'))
        assert finished.wait(2)
        assert [(e.generation, e.kind) for e in events] == [
            (1, SpeechEventKind.STARTED), (1, SpeechEventKind.CANCELLED),
            (2, SpeechEventKind.STARTED), (2, SpeechEventKind.FINISHED),
        ]
        assert played == [b'\0\0', b'\2\0']
        assert launches == [True]
        process.stdin.seek(0)
        read_frame(process.stdin)  # initialize
        assert read_frame(process.stdin)['text'] == 'Old sentence.'
        assert read_frame(process.stdin)['text'] == 'New message.'
    finally:
        speech.shutdown()
        backend.shutdown()


@pytest.mark.usefixtures('fake_model_hashes')
def test_invalid_protocol_and_stale_audio_cleanup(tmp_path):
    _, _, client = modules()
    process = Process([{'type':'hello','engine':'Chatterbox Nano','protocol_version':1}, {'type':'ready','sample_rate':24000}, {'type':'response_end','request_id':2}])
    worker = client.NanoWorkerClient(installation(tmp_path), process_factory=lambda _: process)
    with pytest.raises(client.NanoUnavailable, match='request'):
        list(worker.synthesize('Hello', Event()).chunks)
    assert process.killed

@pytest.mark.usefixtures('fake_model_hashes')
def test_worker_protocol_loads_offline_and_emits_pcm(tmp_path, monkeypatch):
    from piper.nano_worker import main
    from piper.windows_tray.worker_protocol import write_frame, read_frame, decode_audio
    item = installation(tmp_path)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'profile'))
    monkeypatch.delenv('XDG_CACHE_HOME', raising=False)
    monkeypatch.delenv('NUMBA_CACHE_DIR', raising=False)
    model = SimpleNamespace(sr=32000)
    monkeypatch.setattr(main, 'load_model', lambda directory: model)
    monkeypatch.setattr(main, 'generate_chunks', lambda loaded, text: iter([b'\x01\x00']))
    incoming, outgoing = io.BytesIO(), io.BytesIO()
    for frame in ({'type':'initialize','manifest_sha256':item.manifest_sha256}, {'type':'synthesize','request_id':1,'voice_id':'default','text':'Hello'}, {'type':'shutdown'}):
        write_frame(incoming, frame)
    incoming.seek(0)
    main.serve(tmp_path, incoming, outgoing)
    outgoing.seek(0)
    assert read_frame(outgoing) == {
        'type': 'hello',
        'engine': 'Chatterbox Nano',
        'protocol_version': 1,
    }
    assert read_frame(outgoing) == {'type':'ready','sample_rate':32000,'device':'cpu','device_message':''}
    assert decode_audio(read_frame(outgoing)['audio']) == b'\x01\x00'
    assert read_frame(outgoing)['type'] == 'response_end'


@pytest.mark.usefixtures('fake_model_hashes')
def test_worker_uses_requested_device_and_reports_effective_device(tmp_path, monkeypatch):
    from piper.nano_worker import main
    from piper.windows_tray.worker_protocol import write_frame, read_frame
    item = installation(tmp_path)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'profile'))
    monkeypatch.delenv('XDG_CACHE_HOME', raising=False)
    monkeypatch.delenv('NUMBA_CACHE_DIR', raising=False)
    model = SimpleNamespace(sr=32000, effective_device='cuda', device_message=None)
    calls = []
    monkeypatch.setattr(main, 'load_model', lambda directory, device='cpu': calls.append((directory, device)) or model)
    incoming, outgoing = io.BytesIO(), io.BytesIO()
    for frame in ({'type':'initialize','manifest_sha256':item.manifest_sha256,'device':'cuda'}, {'type':'shutdown'}):
        write_frame(incoming, frame)
    incoming.seek(0)
    main.serve(tmp_path, incoming, outgoing)
    outgoing.seek(0)
    assert read_frame(outgoing) == {
        'type': 'hello',
        'engine': 'Chatterbox Nano',
        'protocol_version': 1,
    }
    assert read_frame(outgoing) == {'type':'ready','sample_rate':32000,'device':'cuda','device_message':''}
    assert calls == [(item.model_dir, 'cuda')]


def test_offline_loader_rejects_missing_default_voice(tmp_path):
    _, runtime, _ = modules()
    class Model:
        @classmethod
        def from_local(cls, directory, **kwargs):
            return SimpleNamespace(sr=24000, conds=None)
    with pytest.raises(ValueError, match='default voice'):
        runtime.load_model(tmp_path, model_class=Model)
    import os
    assert os.environ['HF_HUB_OFFLINE'] == '1'


@pytest.mark.usefixtures('fake_model_hashes')
def test_worker_rejects_changed_manifest_identity(tmp_path):
    from piper.nano_worker.main import serve
    from piper.windows_tray.worker_protocol import write_frame
    installation(tmp_path)
    incoming = io.BytesIO()
    write_frame(incoming, {'type':'initialize','manifest_sha256':'0'*64})
    incoming.seek(0)
    with pytest.raises(ValueError, match='identity'):
        serve(tmp_path, incoming, io.BytesIO())


def test_staging_scripts_pin_official_source_and_model():
    assets, _, _ = modules()
    root = Path(__file__).resolve().parents[2]
    lock = json.loads((root / 'script/nano_assets.lock.json').read_text())
    assert lock['source_revision'] == assets.SOURCE_REVISION
    assert lock['model_revision'] == assets.MODEL_REVISION
    assert lock['model_files'] == assets.MODEL_FILE_SHA256
    assert set(lock['model_files']) == set(assets.REQUIRED_MODEL_FILES)
    assert assets.SOURCE_REVISION in (root / 'requirements/nano-worker.in').read_text()


def test_staging_rejects_model_hash_mismatch_before_creating_output(tmp_path, monkeypatch):
    import runpy
    import sys
    assets, _, _ = modules()
    root = Path(__file__).resolve().parents[2]
    worker_dir = tmp_path / 'worker'
    worker_dir.mkdir()
    (worker_dir / 'NanoWorker.exe').write_bytes(b'worker')
    model_dir = tmp_path / 'model'
    model_dir.mkdir()
    for name in assets.REQUIRED_MODEL_FILES:
        (model_dir / name).write_bytes(b'wrong model')
    output = tmp_path / 'payload'
    monkeypatch.setattr(sys, 'argv', [
        'stage_nano_payload.py', '--worker-dir', str(worker_dir),
        '--model-dir', str(model_dir), '--output', str(output),
    ])
    stage = runpy.run_path(str(root / 'script/stage_nano_payload.py'))
    with pytest.raises(ValueError, match='pinned model'):
        stage['main']()
    assert not output.exists()


@pytest.mark.usefixtures('fake_model_hashes')
def test_staging_discards_partial_output_if_model_changes_during_copy(tmp_path, monkeypatch):
    import runpy
    import shutil
    import sys
    assets, _, _ = modules()
    root = Path(__file__).resolve().parents[2]
    worker_dir = tmp_path / 'worker'
    worker_dir.mkdir()
    (worker_dir / 'NanoWorker.exe').write_bytes(b'asset')
    model_dir = tmp_path / 'model'
    model_dir.mkdir()
    for name in assets.REQUIRED_MODEL_FILES:
        (model_dir / name).write_bytes(b'asset')
    changed_file = model_dir / assets.REQUIRED_MODEL_FILES[0]
    output = tmp_path / 'payload'
    monkeypatch.setattr(sys, 'argv', [
        'stage_nano_payload.py', '--worker-dir', str(worker_dir),
        '--model-dir', str(model_dir), '--output', str(output),
    ])
    original_copy2 = shutil.copy2
    def change_before_copy(source, destination, *args, **kwargs):
        if Path(source) == changed_file:
            changed_file.write_bytes(b'changed during staging')
        return original_copy2(source, destination, *args, **kwargs)
    monkeypatch.setattr(shutil, 'copy2', change_before_copy)
    stage = runpy.run_path(str(root / 'script/stage_nano_payload.py'))
    with pytest.raises(ValueError, match='pinned model'):
        stage['main']()
    assert not output.exists()
    assert list(tmp_path.glob('.payload.staging-*')) == []


def test_nano_worker_keeps_librosa_source_for_numba_cache():
    root = Path(__file__).resolve().parents[2]
    spec = (root / 'script/nano_worker.spec').read_text()
    assert "module_collection_mode={'librosa': 'py'}" in spec


def test_nano_worker_bundles_requests_code_and_distribution_metadata():
    root = Path(__file__).resolve().parents[2]
    spec = (root / 'script/nano_worker.spec').read_text()
    assert "'requests')" in spec.split('collect_all(package)', 1)[0]
    assert "'requests')" in spec.split('copy_metadata(package)', 1)[0]


def test_nano_worker_build_installs_cuda_enabled_torch():
    root = Path(__file__).resolve().parents[2]
    script = (root / 'script/build_nano_worker.ps1').read_text()
    assert 'https://download.pytorch.org/whl/cu124' in script
    assert '/whl/cpu' not in script
    assert 'torch==2.6.0+cu124' in script
    assert 'torchaudio==2.6.0+cu124' in script


@pytest.mark.usefixtures('fake_model_hashes')
def test_worker_sets_writable_numba_cache_outside_installation_before_loading(tmp_path, monkeypatch):
    import os
    from piper.nano_worker import main
    from piper.windows_tray.worker_protocol import write_frame
    install_root = tmp_path / 'installation'
    item = installation(install_root)
    user_data = tmp_path / 'profile'
    monkeypatch.setenv('LOCALAPPDATA', str(user_data))
    monkeypatch.delenv('XDG_CACHE_HOME', raising=False)
    monkeypatch.setenv('NUMBA_CACHE_DIR', str(install_root / 'stale-cache'))
    observed = {}
    model = SimpleNamespace(sr=32000)
    def load_model(directory):
        observed['cache_dir'] = Path(os.environ['NUMBA_CACHE_DIR']).resolve()
        assert observed['cache_dir'].is_dir()
        return model
    monkeypatch.setattr(main, 'load_model', load_model)
    incoming, outgoing = io.BytesIO(), io.BytesIO()
    for frame in ({'type':'initialize','manifest_sha256':item.manifest_sha256}, {'type':'shutdown'}):
        write_frame(incoming, frame)
    incoming.seek(0)
    main.serve(install_root, incoming, outgoing)
    cache_dir = observed['cache_dir']
    assert cache_dir == (user_data / 'Piper' / 'Numba').resolve()
    assert install_root.resolve() not in cache_dir.parents
    probe = cache_dir / 'write-test'
    probe.write_bytes(b'ok')
    probe.unlink()


def test_worker_uses_valid_localappdata_when_home_directory_is_unavailable(tmp_path, monkeypatch):
    import os
    from piper.nano_worker import main
    installation_root = tmp_path / 'installation'
    user_data = tmp_path / 'profile'
    monkeypatch.setenv('LOCALAPPDATA', str(user_data))
    monkeypatch.delenv('XDG_CACHE_HOME', raising=False)
    def unavailable_home(cls):
        raise OSError('home directory is unavailable')
    monkeypatch.setattr(Path, 'home', classmethod(unavailable_home))
    cache_dir = main._configure_numba_cache(installation_root)
    assert cache_dir == (user_data / 'Piper' / 'Numba').resolve()
    assert os.environ['NUMBA_CACHE_DIR'] == str(cache_dir)


@pytest.mark.usefixtures('fake_model_hashes')
def test_oversized_text_and_invalid_ready_stop_process(tmp_path):
    _, _, client = modules()
    process = Process([{'type':'hello','engine':'Chatterbox Nano','protocol_version':1}, {'type':'ready','sample_rate':True}])
    worker = client.NanoWorkerClient(installation(tmp_path), process_factory=lambda _: process)
    with pytest.raises(client.NanoUnavailable, match='ready'):
        worker.ensure_ready()
    assert process.killed


@pytest.mark.usefixtures('fake_model_hashes')
def test_cancel_during_blocked_inference_stops_promptly(tmp_path):
    import threading
    import time
    from piper.windows_tray.worker_protocol import write_frame
    _, _, client = modules()
    process = Process([])
    reader, writer = __import__('os').pipe()
    process.stdout = __import__('os').fdopen(reader, 'rb', buffering=0)
    pipe = __import__('os').fdopen(writer, 'wb', buffering=0)
    for frame in ({'type':'hello','engine':'Chatterbox Nano','protocol_version':1}, {'type':'ready','sample_rate':24000}):
        write_frame(pipe, frame)
    original_terminate = process.terminate
    def terminate():
        original_terminate()
        pipe.close()
    process.terminate = terminate
    worker = client.NanoWorkerClient(installation(tmp_path), process_factory=lambda _: process)
    cancel = Event()
    chunks = worker.synthesize('Hello', cancel).chunks
    timer = threading.Timer(.08, cancel.set)
    timer.start()
    started = time.monotonic()
    assert list(chunks) == []
    assert time.monotonic() - started < 1
    assert not process.killed
    worker.shutdown()
    pipe.close()
    timer.join()


@pytest.mark.usefixtures('fake_model_hashes')
def test_reader_preserves_eof_when_audio_queue_is_full(tmp_path):
    import time
    from piper.windows_tray.worker_protocol import encode_audio
    _, _, client = modules()
    frames = [{'type':'hello','engine':'Chatterbox Nano','protocol_version':1}, {'type':'ready','sample_rate':24000}]
    frames += [{'type':'audio','request_id':1,'audio':encode_audio(b'\0\0')} for _ in range(20)]
    process = Process(frames)
    worker = client.NanoWorkerClient(installation(tmp_path), process_factory=lambda _: process)
    result = worker.synthesize('Hello', Event())
    time.sleep(.1)
    with pytest.raises(client.NanoUnavailable, match='protocol'):
        list(result.chunks)
    assert process.killed

@pytest.mark.usefixtures('fake_model_hashes')
def test_discarded_uniterated_result_does_not_poison_next_request(tmp_path):
    _, _, client = modules()
    process = Process([{'type':'hello','engine':'Chatterbox Nano','protocol_version':1}, {'type':'ready','sample_rate':24000}, {'type':'response_end','request_id':2}])
    worker = client.NanoWorkerClient(installation(tmp_path), process_factory=lambda _: process)
    discarded = worker.synthesize('Never played', Event())
    discarded.chunks.close()
    assert list(worker.synthesize('Played', Event()).chunks) == []
    worker.shutdown()

def test_correct_manifest_cannot_relabel_wrong_model_as_pinned(tmp_path, fake_model_hashes, monkeypatch):
    assets, _, _ = modules()
    item = installation(tmp_path)
    model = item.model_dir / assets.REQUIRED_MODEL_FILES[0]
    model.write_bytes(b'wrong model')
    manifest_path = tmp_path / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['files']['model/' + model.name] = assets.file_sha256(model)
    manifest_path.write_text(json.dumps(manifest))
    monkeypatch.setattr(assets, 'MODEL_FILE_SHA256', fake_model_hashes)
    with pytest.raises(ValueError, match='pinned model'):
        assets.inspect_nano_installation(tmp_path)
