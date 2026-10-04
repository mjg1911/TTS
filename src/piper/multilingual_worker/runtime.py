"""Offline V3 loading and bounded multilingual inference."""
import os
from pathlib import Path

from piper.multilingual_options import validate_language, validate_exaggeration, validate_cfg_weight
from piper.nano_worker.runtime import pcm16, split_text


def _configure_chinese_segmenter(directory):
    """Point upstream segmentation at staged files and forbid its downloader."""
    import spacy_pkuseg

    cache = Path(directory) / 'pkuseg'
    spacy_pkuseg.config.pkuseg_home = str(cache)

    def require_local_model(url, model_dir, hash_prefix, progress=True):
        if Path(model_dir) != cache or not (cache / 'spacy_ontonotes').is_dir():
            raise RuntimeError('Chinese segmenter is missing from the offline Multilingual payload.')
        # The installation inspector validates the staged model's pinned hashes.
        # pkuseg calls download_model even when its model is already cached.
    spacy_pkuseg.download_model = require_local_model


def load_model(directory, model_class=None, torch_module=None, reference_clip=None, exaggeration=0.5):
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    exaggeration = validate_exaggeration(exaggeration)
    if torch_module is None:
        import torch as torch_module
    if not torch_module.cuda.is_available():
        raise RuntimeError('Chatterbox Multilingual requires an NVIDIA GPU with CUDA. CPU fallback is disabled.')
    if model_class is None:
        _configure_chinese_segmenter(directory)
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        model_class = ChatterboxMultilingualTTS
    model = model_class.from_local(Path(directory), device='cuda', t3_model='v3')
    if reference_clip is not None:
        reference_path = Path(reference_clip).expanduser()
        if not reference_path.is_absolute():
            raise ValueError('Multilingual reference clip must be an absolute WAV path')
        reference_path = reference_path.resolve(strict=True)
        if not reference_path.is_file() or reference_path.suffix.lower() != '.wav':
            raise ValueError('Multilingual reference clip must be an existing WAV file')
        model.prepare_conditionals(reference_path, exaggeration=exaggeration)
    if model.conds is None:
        raise ValueError('Multilingual voice conditionals are missing')
    if type(model.sr) is not int or not 8000 <= model.sr <= 192000:
        raise ValueError('Invalid Multilingual sample rate')
    model.effective_device = 'cuda'
    model.device_message = 'Multilingual V3 uses GPU (CUDA).'
    return model


def generate_chunks(model, text, language='en', exaggeration=0.5, cfg_weight=0.5):
    language = validate_language(language)
    exaggeration = validate_exaggeration(exaggeration)
    cfg_weight = validate_cfg_weight(cfg_weight)
    for piece in split_text(text):
        audio = pcm16(model.generate(piece, language_id=language, exaggeration=exaggeration, cfg_weight=cfg_weight))
        for offset in range(0, len(audio), 65536):
            yield audio[offset:offset + 65536]
