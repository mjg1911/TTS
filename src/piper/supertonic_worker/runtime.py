"""Pinned Supertonic 3 inference through a selected ONNX Runtime provider."""

from dataclasses import dataclass
import importlib
import os
from pathlib import Path
import sys

from piper.supertonic_options import (
    DEFAULT_LANGUAGE,
    DEFAULT_DEVICE,
    validate_device,
    DEFAULT_VOICE,
    validate_language,
    validate_voice,
)
from piper.nano_worker.runtime import pcm16


CUDA_PROVIDER = 'CUDAExecutionProvider'
CPU_PROVIDER = 'CPUExecutionProvider'
SAMPLE_RATE_MIN = 8000
SAMPLE_RATE_MAX = 192000
MAX_AUDIO_CHUNK_BYTES = 65536
_CUDA_DLL_DIRECTORY_HANDLES = []
_CUDA_DLL_DIRECTORIES = set()


@dataclass(frozen=True)
class LoadedSupertonic:
    tts: object
    voice_style: object
    language: str
    sample_rate: int


def _get_sdk_components(tts_class, loader_module):
    if loader_module is None:
        loader_module = importlib.import_module('supertonic.loader')
    if tts_class is None:
        package = importlib.import_module('supertonic')
        tts_class = package.TTS
    return tts_class, loader_module


def _add_frozen_cuda_library_directories():
    """Expose bundled NVIDIA wheel DLLs to ONNX Runtime in a frozen worker."""
    if not getattr(sys, 'frozen', False) or not hasattr(os, 'add_dll_directory'):
        return
    bundled_nvidia = Path(sys._MEIPASS) / 'nvidia'
    if not bundled_nvidia.is_dir():
        return
    for library in bundled_nvidia.rglob('*.dll'):
        directory = library.parent
        directory_string = str(directory)
        if directory_string not in _CUDA_DLL_DIRECTORIES:
            _CUDA_DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(str(directory)))
            _CUDA_DLL_DIRECTORIES.add(directory_string)


def _validate_sessions(model, provider):
    sessions = (
        ('duration predictor', getattr(model, 'dp_ort', None)),
        ('text encoder', getattr(model, 'text_enc_ort', None)),
        ('vector estimator', getattr(model, 'vector_est_ort', None)),
        ('vocoder', getattr(model, 'vocoder_ort', None)),
    )
    for name, session in sessions:
        get_providers = getattr(session, 'get_providers', None)
        providers = get_providers() if callable(get_providers) else ()
        if not providers or providers[0] != provider:
            raise RuntimeError(
                f'Supertonic 3 {name} did not load with {provider}; '
                'automatic device fallback is disabled.'
            )
        disable_fallback = getattr(session, 'disable_fallback', None)
        if callable(disable_fallback):
            disable_fallback()


def load_model(
    directory,
    *,
    voice=DEFAULT_VOICE,
    language=DEFAULT_LANGUAGE,
    device=DEFAULT_DEVICE,
    tts_class=None,
    onnxruntime_module=None,
    loader_module=None,
):
    """Load the SDK with the selected device as its execution provider."""
    device = validate_device(device)
    provider = CUDA_PROVIDER if device == 'cuda' else CPU_PROVIDER
    voice = validate_voice(voice)
    language = validate_language(language)
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    if device == 'cuda':
        _add_frozen_cuda_library_directories()

    if onnxruntime_module is None:
        onnxruntime_module = importlib.import_module('onnxruntime')
    if device == 'cuda' and callable(getattr(onnxruntime_module, 'preload_dlls', None)):
        # ONNX Runtime can load its CUDA/cuDNN dependencies from installed
        # NVIDIA wheels before creating its first session.
        onnxruntime_module.preload_dlls()
    available = onnxruntime_module.get_available_providers()
    if provider not in available:
        raise RuntimeError(
            f'Supertonic 3 requires ONNX Runtime {provider} for {device}. '
            'Automatic device fallback is disabled.'
        )

    tts_class, loader_module = _get_sdk_components(tts_class, loader_module)
    previous_providers = loader_module.DEFAULT_ONNX_PROVIDERS
    loader_module.DEFAULT_ONNX_PROVIDERS = [provider]
    try:
        try:
            tts = tts_class(
                model='supertonic-3',
                model_dir=Path(directory),
                auto_download=False,
            )
        except Exception as error:
            raise RuntimeError(
                ('Supertonic 3 CUDA initialization failed. Verify that the NVIDIA '
                 'CUDA and cuDNN runtime libraries are available. CPU fallback is disabled.')
                if device == 'cuda' else 'Supertonic 3 CPU initialization failed.'
            ) from error
    finally:
        loader_module.DEFAULT_ONNX_PROVIDERS = previous_providers

    try:
        _validate_sessions(tts.model, provider)
        sample_rate = tts.sample_rate
        if type(sample_rate) is not int or not SAMPLE_RATE_MIN <= sample_rate <= SAMPLE_RATE_MAX:
            raise ValueError('invalid Supertonic 3 sample rate')
        voice_style = tts.get_voice_style(voice)
    except Exception:
        raise

    return LoadedSupertonic(
        tts=tts,
        voice_style=voice_style,
        language=language,
        sample_rate=sample_rate,
    )


def generate_chunks(model, text):
    """Synthesize with the prepared style and yield bounded little-endian PCM16."""
    waveform, _duration = model.tts.synthesize(
        text,
        voice_style=model.voice_style,
        total_steps=8,
        lang=model.language,
    )
    audio = pcm16(waveform)
    for offset in range(0, len(audio), MAX_AUDIO_CHUNK_BYTES):
        yield audio[offset:offset + MAX_AUDIO_CHUNK_BYTES]
