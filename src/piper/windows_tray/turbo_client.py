"""Tray-side Turbo worker client sharing the bounded worker lifecycle."""
from piper.turbo_options import ENGINE
from .nano_client import NanoWorkerClient, NanoUnavailable, launch_nano_worker


def launch_turbo_worker(installation):
    return launch_nano_worker(
        installation,
        python_env='PIPER_TURBO_WORKER_PYTHON',
        module='piper.turbo_worker.main',
    )


class TurboWorkerClient(NanoWorkerClient):
    engine = ENGINE

    def __init__(self, installation, process_factory=launch_turbo_worker, *, reference_clip=None):
        super().__init__(
            installation,
            process_factory=process_factory,
            device='cuda',
            reference_clip=reference_clip,
        )

    def _validate_engine_ready(self, ready):
        if ready.get('type') == 'startup_error':
            message = ready.get('message')
            raise NanoUnavailable(message if isinstance(message, str) and message else 'Turbo GPU initialization failed.')
        if ready.get('device') != 'cuda':
            raise NanoUnavailable('Turbo requires CUDA; CPU fallback is disabled.')
