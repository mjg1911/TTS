"""Exercise real clients and preparation across modes of one executable."""
from types import SimpleNamespace

import pytest

from piper.windows_tray import app, nano_client
from piper.windows_tray.backend_manager import BackendManager, BackendPreparationError
from tests.windows_tray.test_nano_runtime import Process


def test_switch_restarts_shared_executable_and_failure_preserves_current_backend(monkeypatch, tmp_path):
    shared = tmp_path / 'Chatterbox'
    executable = shared / 'worker' / 'ChatterboxWorker.exe'
    processes, commands = [], []
    fail_turbo = [False]

    def installation(engine):
        return SimpleNamespace(root=shared, worker_executable=executable,
                               model_dir=shared / 'models' / engine,
                               manifest_sha256='a' * 64)

    monkeypatch.setattr(app, '_prepare_nano_installation', lambda: installation('nano'))
    monkeypatch.setattr(app, '_prepare_turbo_installation', lambda: installation('turbo'))
    for name in ('PIPER_CHATTERBOX_WORKER_PYTHON', 'PIPER_NANO_WORKER_PYTHON', 'PIPER_TURBO_WORKER_PYTHON'):
        monkeypatch.delenv(name, raising=False)

    class Job:
        def assign(self, process):
            pass

        def close(self):
            pass

    def launch(command, **options):
        commands.append(command)
        mode = command[command.index('--engine') + 1]
        engine = 'Chatterbox Nano' if mode == 'nano' else 'Chatterbox Turbo (350M)'
        ready = ({'type': 'startup_error', 'message': 'CUDA unavailable'}
                 if mode == 'turbo' and fail_turbo[0]
                 else {'type': 'ready', 'sample_rate': 24000,
                       'device': 'cpu' if mode == 'nano' else 'cuda'})
        process = Process([{'type': 'hello', 'engine': engine, 'protocol_version': 1}, ready])
        processes.append(process)
        return process

    monkeypatch.setattr(nano_client.subprocess, 'Popen', launch)
    monkeypatch.setattr(nano_client, 'WindowsKillOnCloseJob', Job)
    prepare = lambda engine, voice: (app._prepare_nano_backend() if engine == 'Chatterbox Nano'
                                    else app._prepare_turbo_backend(delivery_mode='[whispering]'))
    piper = object()
    manager = BackendManager('Piper', 'saved.onnx', piper, lambda: None, prepare)
    nano = manager.prepare('Chatterbox Nano', 'default')
    manager.commit(nano)
    assert manager.current().effective_device == 'cpu'
    turbo = manager.prepare('Chatterbox Turbo (350M)', 'default')
    manager.commit(turbo)
    assert processes[0].killed
    assert manager.current().effective_device == 'cuda'
    assert manager.current()._synthesis_options() == {'delivery_mode': '[whispering]'}
    manager.commit(manager.prepare('Chatterbox Nano', 'default'))
    assert processes[1].killed
    current = manager.current()
    fail_turbo[0] = True
    with pytest.raises(BackendPreparationError, match='CUDA unavailable'):
        manager.prepare('Chatterbox Turbo (350M)', 'default')
    assert manager.current() is current
    assert not processes[2].killed
    assert processes[3].killed
    assert {command[0] for command in commands} == {str(executable)}
    assert [command[command.index('--model-dir') + 1] for command in commands] == [
        str(shared / 'models' / mode) for mode in ('nano', 'turbo', 'nano', 'turbo')]
    manager.shutdown()
    assert processes[2].killed
