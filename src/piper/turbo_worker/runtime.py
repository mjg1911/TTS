"""Offline CUDA-only Turbo loading and bounded audio generation."""
import os
from pathlib import Path

from piper.nano_worker.runtime import pcm16, split_text


def _resolve_reference_clip(reference_clip):
    try:
        path = Path(reference_clip).expanduser()
        if not path.is_absolute():
            raise ValueError('reference clip must be absolute')
        path = path.resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise ValueError('Turbo reference clip must be an existing absolute WAV file') from error
    if not path.is_file() or path.suffix.lower() != '.wav':
        raise ValueError('Turbo reference clip must be an existing absolute WAV file')
    return path


def load_model(directory, model_class=None, torch_module=None, reference_clip=None):
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    if torch_module is None:
        import torch as torch_module
    if not torch_module.cuda.is_available():
        raise RuntimeError('Chatterbox Turbo requires an NVIDIA GPU with CUDA. CPU fallback is disabled.')
    reference_path = None if reference_clip is None else _resolve_reference_clip(reference_clip)
    if model_class is None:
        from chatterbox.tts_turbo import ChatterboxTurboTTS
        model_class = ChatterboxTurboTTS
    model = model_class.from_local(Path(directory), device='cuda', nano=False)
    if reference_path is not None:
        model.prepare_conditionals(reference_path)
    if model.conds is None:
        voice_kind = 'custom' if reference_path is not None else 'default'
        raise ValueError(f'Turbo {voice_kind} voice conditionals are missing')
    if type(model.sr) is not int or not 8000 <= model.sr <= 192000:
        raise ValueError('invalid Turbo sample rate')
    model.effective_device = 'cuda'
    model.device_message = 'Chatterbox Turbo (350M) uses GPU (CUDA).'
    return model


def generate_chunks(model, text, torch_module=None, delivery_mode=''):
    if torch_module is None:
        import torch as torch_module
    for piece in split_text(text):
        with torch_module.inference_mode():
            generation_text = f'{delivery_mode} {piece}' if delivery_mode else piece
            audio = pcm16(model.generate(generation_text))
        for offset in range(0, len(audio), 65536):
            yield audio[offset:offset + 65536]
