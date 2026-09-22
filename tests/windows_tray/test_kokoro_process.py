import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from piper.windows_tray.kokoro_client import KokoroWorkerConfig
from piper.windows_tray.kokoro_process import (
    CREATE_NO_WINDOW,
    WindowsKillOnCloseJob,
    launch_kokoro_worker,
)


def _config():
    return KokoroWorkerConfig(
        executable=Path(r"C:\Piper\KokoroWorker.exe"),
        install_root=Path(r"C:\Piper\Kokoro"),
        manifest_sha256="a" * 64,
        worker_version="1",
        kokoro_version="0.9.4",
    )


def test_launch_uses_hidden_inherited_pipes_and_assigns_job():
    calls = {}
    process = SimpleNamespace(_handle=123)

    def fake_popen(argv, **kwargs):
        calls["argv"] = argv
        calls["kwargs"] = kwargs
        return process

    class FakeJob:
        def __init__(self):
            calls["job"] = self
            self.assigned = []

        def assign(self, candidate):
            self.assigned.append(candidate)

        def close(self):
            calls["closed"] = True

    launched = launch_kokoro_worker(
        _config(),
        popen=fake_popen,
        job_factory=FakeJob,
    )

    assert launched is process
    assert calls["argv"] == [str(_config().executable)]
    assert calls["kwargs"]["stdin"] is subprocess.PIPE
    assert calls["kwargs"]["stdout"] is subprocess.PIPE
    assert calls["kwargs"]["stderr"] is subprocess.PIPE
    assert calls["kwargs"]["creationflags"] & CREATE_NO_WINDOW
    assert calls["job"].assigned == [process]
    assert process._piper_kokoro_job is calls["job"]


def test_launch_failure_kills_process_and_closes_job():
    calls = []
    process = SimpleNamespace(_handle=123, kill=lambda: calls.append("kill"))

    class FailingJob:
        def assign(self, candidate):
            calls.append(("assign", candidate))
            raise OSError("assignment failed")

        def close(self):
            calls.append("close")

    with pytest.raises(OSError, match="assignment failed"):
        launch_kokoro_worker(
            _config(),
            popen=lambda *_args, **_kwargs: process,
            job_factory=FailingJob,
        )

    assert calls == [("assign", process), "kill", "close"]


def test_job_close_is_idempotent():
    closed = []
    job = WindowsKillOnCloseJob(
        create_job=lambda: 77,
        configure_job=lambda handle: None,
        assign_process=lambda handle, process_handle: None,
        close_handle=lambda handle: closed.append(handle),
    )

    job.close()
    job.close()

    assert closed == [77]
