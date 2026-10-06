"""Tray-side Turbo worker client sharing the bounded worker lifecycle."""
from pathlib import Path

from piper.turbo_options import ENGINE, validate_delivery_mode
from .nano_client import NanoWorkerClient, NanoUnavailable, launch_nano_worker


def launch_turbo_worker(installation):
    options = {
        'python_env': 'PIPER_TURBO_WORKER_PYTHON',
        'module': 'piper.turbo_worker.main',
    }
    if Path(installation.worker_executable).name == 'ChatterboxWorker.exe':
        options['engine'] = 'turbo'
    return launch_nano_worker(installation, **options)


class TurboWorkerClient(NanoWorkerClient):
    engine = ENGINE

    def __init__(
        self,
        installation,
        process_factory=launch_turbo_worker,
        *,
        reference_clip=None,
        delivery_mode='',
    ):
        self.delivery_mode = validate_delivery_mode(delivery_mode)
        super().__init__(
            installation,
            process_factory=process_factory,
            device='cuda',
            reference_clip=reference_clip,
        )

    def set_delivery_mode(self, delivery_mode):
        self.delivery_mode = validate_delivery_mode(delivery_mode)

    def _synthesis_options(self):
        return {'delivery_mode': self.delivery_mode} if self.delivery_mode else {}

    def _validate_engine_ready(self, ready):
        if ready.get('type') == 'startup_error':
            message = ready.get('message')
            raise NanoUnavailable(message if isinstance(message, str) and message else 'Turbo GPU initialization failed.')
        if ready.get('device') != 'cuda':
            raise NanoUnavailable('Turbo requires CUDA; CPU fallback is disabled.')
