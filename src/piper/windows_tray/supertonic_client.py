"""Tray-side client for the isolated Supertonic 3 worker."""

from pathlib import Path
import os
import subprocess
import sys

from piper.supertonic_options import (
    DEFAULT_LANGUAGE,
    DEFAULT_DEVICE,
    validate_device,
    DEFAULT_VOICE,
    ENGINE,
    validate_language,
    validate_voice,
)
from .nano_client import NanoUnavailable, NanoWorkerClient
from .worker_process import CREATE_NO_WINDOW, WindowsKillOnCloseJob


def launch_supertonic_worker(installation):
    """Launch the development Python worker or packaged worker executable."""
    python = os.environ.get('PIPER_SUPERTONIC_WORKER_PYTHON')
    worker_args = ['--root', str(installation.root)]
    bundled_root = getattr(sys, '_MEIPASS', None)
    bundled_worker = (
        Path(bundled_root) / 'supertonic_worker' / 'SupertonicWorker.exe'
        if bundled_root else None
    )
    packaged_worker = (
        bundled_worker
        if bundled_worker is not None and bundled_worker.is_file()
        else installation.worker_executable
    )
    command = [python, '-m', 'piper.supertonic_worker.main'] if python else [str(packaged_worker)]
    environment = os.environ.copy()
    environment.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    if python:
        source_root = str(Path(__file__).resolve().parents[2])
        existing_path = environment.get('PYTHONPATH')
        environment['PYTHONPATH'] = (
            source_root if not existing_path else source_root + os.pathsep + existing_path
        )

    process = subprocess.Popen(
        command + worker_args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=environment,
        creationflags=CREATE_NO_WINDOW if os.name == 'nt' else 0,
    )
    if os.name == 'nt':
        job = None
        try:
            job = WindowsKillOnCloseJob()
            job.assign(process)
            process._nano_job = job
        except BaseException:
            try:
                try:
                    process.kill()
                except Exception:
                    pass
                try:
                    process.wait(timeout=1)
                except Exception:
                    pass
            finally:
                if job is not None:
                    try:
                        job.close()
                    except Exception:
                        pass
            raise
    return process


class SupertonicWorkerClient(NanoWorkerClient):
    """Bounded framed-protocol client for the explicitly selected device."""

    engine = ENGINE

    def __init__(
        self,
        installation,
        process_factory=launch_supertonic_worker,
        *,
        voice=DEFAULT_VOICE,
        language=DEFAULT_LANGUAGE,
        device=DEFAULT_DEVICE,
    ):
        self.voice = validate_voice(voice)
        self.language = validate_language(language)
        super().__init__(installation, process_factory=process_factory, device=validate_device(device))

    def _initialize_message(self):
        return {
            'type': 'initialize',
            'manifest_sha256': self.installation.manifest_sha256,
            'device': self.device,
            'voice': self.voice,
            'language': self.language,
        }

    def _validate_engine_ready(self, ready):
        if ready.get('type') == 'startup_error':
            message = ready.get('message')
            raise NanoUnavailable(
                message if isinstance(message, str) and message
                else f'Supertonic 3 {self.device} initialization failed.'
            )
        if ready.get('device') != self.device:
            raise NanoUnavailable(
                f'Supertonic 3 requires the selected {self.device.upper()} device; '
                'automatic device fallback is disabled.'
            )
