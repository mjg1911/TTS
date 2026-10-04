"""Multilingual protocol configuration using the shared worker lifecycle."""
from piper.multilingual_options import ENGINE, validate_language, validate_exaggeration, validate_cfg_weight
from .nano_client import NanoWorkerClient, NanoUnavailable, launch_nano_worker


def launch_multilingual_worker(installation):
    return launch_nano_worker(installation, python_env='PIPER_MULTILINGUAL_WORKER_PYTHON', module='piper.multilingual_worker.main')


class MultilingualWorkerClient(NanoWorkerClient):
    engine = ENGINE

    def __init__(self, installation, process_factory=launch_multilingual_worker, *, language='en', exaggeration=0.5, cfg_weight=0.5, reference_clip=None):
        self.language = validate_language(language)
        self.exaggeration = validate_exaggeration(exaggeration)
        self.cfg_weight = validate_cfg_weight(cfg_weight)
        super().__init__(installation, process_factory=process_factory, device='cuda', reference_clip=reference_clip)

    def _initialize_message(self):
        return dict(super()._initialize_message(), language=self.language, exaggeration=self.exaggeration, cfg_weight=self.cfg_weight)

    def _validate_engine_ready(self, ready):
        if ready.get('type') == 'startup_error':
            message = ready.get('message')
            raise NanoUnavailable(message if isinstance(message, str) and message else 'Multilingual GPU initialization failed.')
        if ready.get('device') != 'cuda':
            raise NanoUnavailable('Multilingual requires CUDA; CPU fallback is disabled.')
