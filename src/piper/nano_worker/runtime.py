"""Local-only inference and bounded English text preparation."""
import os
import re
from pathlib import Path


def split_text(text, max_bytes=240):
    text = ' '.join(text.split())
    while text:
        end = min(len(text), max_bytes)
        while len(text[:end].encode('utf8')) > max_bytes:
            end -= 1
        if end == 0:
            raise ValueError('text chunk limit too small')
        if end < len(text):
            boundaries = [match.end() for match in re.finditer(r'[.!?]\s+|\s+', text[:end])]
            if boundaries:
                end = boundaries[-1]
            # Preserve a bracketed paralinguistic tag at a boundary.
            opening = text.rfind('[', 0, end)
            closing = text.rfind(']', 0, end)
            if opening > closing and opening > 0:
                end = opening
        piece, text = text[:end].strip(), text[end:].strip()
        if piece:
            yield piece


def pcm16(waveform):
    import numpy as np
    if hasattr(waveform, 'detach'):
        waveform = waveform.detach().cpu().numpy()
    value = np.asarray(waveform).squeeze()
    if value.ndim > 1 or not np.isfinite(value).all():
        raise ValueError('Nano waveform must be finite mono audio')
    return np.clip(value * 32768, -32768, 32767).astype('<i2').tobytes()


def resolve_device(device, torch_module=None):
    if device not in ('cpu', 'cuda'):
        raise ValueError('Nano device must be cpu or cuda')
    if device == 'cpu':
        return 'cpu', None
    if torch_module is None:
        try:
            import torch as torch_module
        except ImportError:
            return 'cpu', 'CUDA unavailable; using CPU.'
    try:
        available = torch_module.cuda.is_available()
    except (AttributeError, RuntimeError):
        available = False
    if not available:
        return 'cpu', 'CUDA unavailable; using CPU.'
    return 'cuda', ''


def load_model(directory, model_class=None, device='cpu', reference_clip=None):
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    if model_class is None:
        from chatterbox.tts_turbo import ChatterboxTurboTTS
        model_class = ChatterboxTurboTTS
    effective_device, device_message = resolve_device(device)
    model = model_class.from_local(Path(directory), device=effective_device, nano=True)
    if reference_clip is not None:
        try:
            reference_path = Path(reference_clip).expanduser()
            if not reference_path.is_absolute():
                raise ValueError('Nano reference clip must be an absolute WAV path')
            reference_path = reference_path.resolve(strict=True)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            raise ValueError('Nano reference clip must be an existing absolute WAV file') from error
        if not reference_path.is_absolute() or not reference_path.is_file() or reference_path.suffix.lower() != '.wav':
            raise ValueError('Nano reference clip must be an existing absolute WAV file')
        model.prepare_conditionals(reference_path, exaggeration=0.0)
        if model.conds is None:
            raise ValueError('Nano custom voice conditionals are missing')
    elif model.conds is None:
        raise ValueError('Nano default voice conditionals are missing')
    if type(model.sr) is not int or not 8000 <= model.sr <= 192000:
        raise ValueError('invalid Nano sample rate')
    model.effective_device = effective_device
    model.device_message = device_message or ''
    return model


def generate_chunks(model, text):
    import torch
    from chatterbox.tts_turbo import punc_norm
    for piece in split_text(text):
        # Check the exact normalized tokenizer input before upstream truncation.
        tokens = model.tokenizer(punc_norm(piece), truncation=False)['input_ids']
        limit = min(getattr(model.tokenizer, 'model_max_length', 512), 256)
        if len(tokens) > limit:
            raise ValueError('Nano text exceeds tokenizer limit')
        with torch.inference_mode():
            audio = pcm16(model.generate(piece))
        for offset in range(0, len(audio), 65536):
            yield audio[offset:offset + 65536]
