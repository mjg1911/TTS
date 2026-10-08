from types import SimpleNamespace

import numpy as np
import pytest

from piper.supertonic_worker import runtime


class _Session:
    def __init__(self, providers=('CUDAExecutionProvider', 'CPUExecutionProvider')):
        self._providers = list(providers)
        self.fallback_disabled = False

    def get_providers(self):
        return self._providers

    def disable_fallback(self):
        self.fallback_disabled = True


def _fake_tts(
    *, providers=('CUDAExecutionProvider', 'CPUExecutionProvider'), sample_rate=44100,
    on_init=None,
):
    calls = []
    engine = SimpleNamespace(
        sample_rate=sample_rate,
        dp_ort=_Session(providers),
        text_enc_ort=_Session(providers),
        vector_est_ort=_Session(providers),
        vocoder_ort=_Session(providers),
    )
    style = object()

    class TTS:
        def __init__(self, **kwargs):
            calls.append(kwargs)
            if on_init is not None:
                on_init()
            self.model = engine
            self.sample_rate = sample_rate

        def get_voice_style(self, voice):
            calls.append(('voice', voice))
            return style

    return TTS, calls, engine, style


def _fake_ort(providers):
    return SimpleNamespace(get_available_providers=lambda: providers)


def test_cpu_loads_without_cuda_setup(tmp_path, monkeypatch):
    loader = SimpleNamespace(DEFAULT_ONNX_PROVIDERS=['CUDAExecutionProvider'])
    observed = []
    tts, _, _, _ = _fake_tts(
        providers=('CPUExecutionProvider',),
        on_init=lambda: observed.append(list(loader.DEFAULT_ONNX_PROVIDERS)),
    )
    def unexpected_cuda_setup():
        pytest.fail('CPU must not set up CUDA libraries')
    monkeypatch.setattr(runtime, '_add_frozen_cuda_library_directories', unexpected_cuda_setup)
    ort = _fake_ort(['CPUExecutionProvider'])
    ort.preload_dlls = unexpected_cuda_setup
    model = runtime.load_model(tmp_path, device='cpu', tts_class=tts,
                               onnxruntime_module=ort, loader_module=loader)
    assert model.sample_rate == 44100
    assert observed == [['CPUExecutionProvider']]
    assert loader.DEFAULT_ONNX_PROVIDERS == ['CUDAExecutionProvider']


def test_cpu_selection_rejects_a_session_using_gpu(tmp_path):
    loader = SimpleNamespace(DEFAULT_ONNX_PROVIDERS=['CPUExecutionProvider'])
    tts, _, _, _ = _fake_tts()
    with pytest.raises(RuntimeError, match='CPUExecutionProvider'):
        runtime.load_model(tmp_path, device='cpu', tts_class=tts,
                           onnxruntime_module=_fake_ort(['CPUExecutionProvider']),
                           loader_module=loader)


def test_loads_pinned_sdk_offline_and_requires_cuda_before_ready(tmp_path):
    loader = SimpleNamespace(DEFAULT_ONNX_PROVIDERS=['CPUExecutionProvider'])
    ort = _fake_ort(['CUDAExecutionProvider', 'CPUExecutionProvider'])
    observed_during_init = []

    def inspect_cuda_configuration():
        observed_during_init.append(list(loader.DEFAULT_ONNX_PROVIDERS))

    tts_class, calls, _engine, style = _fake_tts(
        on_init=inspect_cuda_configuration,
    )

    model = runtime.load_model(
        tmp_path, voice='F2', language='nl', tts_class=tts_class,
        onnxruntime_module=ort, loader_module=loader,
    )

    assert calls == [
        {'model': 'supertonic-3', 'model_dir': tmp_path, 'auto_download': False},
        ('voice', 'F2'),
    ]
    assert model.voice_style is style
    assert model.language == 'nl'
    assert model.sample_rate == 44100
    assert observed_during_init == [['CUDAExecutionProvider']]
    assert all(session.fallback_disabled for session in (
        _engine.dp_ort, _engine.text_enc_ort, _engine.vector_est_ort, _engine.vocoder_ort,
    ))
    assert loader.DEFAULT_ONNX_PROVIDERS == ['CPUExecutionProvider']


def test_missing_cuda_fails_before_constructing_the_sdk(tmp_path):
    tts_class, calls, *_ = _fake_tts()
    ort = _fake_ort(['CPUExecutionProvider'])
    loader = SimpleNamespace(DEFAULT_ONNX_PROVIDERS=['CPUExecutionProvider'])

    with pytest.raises(RuntimeError, match='CUDAExecutionProvider'):
        runtime.load_model(
            tmp_path, tts_class=tts_class, onnxruntime_module=ort, loader_module=loader,
        )

    assert calls == []


def test_sdk_session_that_did_not_select_cuda_is_rejected(tmp_path):
    tts_class, calls, *_ = _fake_tts(providers=('CPUExecutionProvider',))
    ort = _fake_ort(['CUDAExecutionProvider', 'CPUExecutionProvider'])
    loader = SimpleNamespace(DEFAULT_ONNX_PROVIDERS=['CPUExecutionProvider'])

    with pytest.raises(RuntimeError, match='CUDAExecutionProvider'):
        runtime.load_model(
            tmp_path, tts_class=tts_class, onnxruntime_module=ort, loader_module=loader,
        )

    assert calls[0]['auto_download'] is False


def test_generation_uses_prepared_voice_language_and_splits_pcm16_chunks():
    calls = []
    audio = np.full((1, 40000), 0.25, dtype=np.float32)
    model = runtime.LoadedSupertonic(
        tts=SimpleNamespace(synthesize=lambda *args, **kwargs: calls.append((args, kwargs)) or (audio, np.array([1.0]))),
        voice_style=object(), language='de', sample_rate=44100,
    )

    chunks = list(runtime.generate_chunks(model, 'Hallo zusammen.'))

    assert len(calls) == 1
    assert calls[0][0] == ('Hallo zusammen.',)
    assert calls[0][1]['voice_style'] is model.voice_style
    assert calls[0][1]['lang'] == 'de'
    assert calls[0][1]['total_steps'] == 8
    assert len(chunks) >= 2
    assert all(0 < len(chunk) <= 65536 and len(chunk) % 2 == 0 for chunk in chunks)


def test_frozen_runtime_registers_bundled_nvidia_dll_directories(tmp_path, monkeypatch):
    import sys

    cuda_dir = tmp_path / 'nvidia' / 'cu13' / 'bin' / 'x86_64'
    cudnn_dir = tmp_path / 'nvidia' / 'cudnn' / 'bin'
    cuda_dir.mkdir(parents=True)
    cudnn_dir.mkdir(parents=True)
    (cuda_dir / 'cublas64_13.dll').write_bytes(b'fixture')
    (cudnn_dir / 'cudnn64_9.dll').write_bytes(b'fixture')
    added = []
    handles = runtime._CUDA_DLL_DIRECTORY_HANDLES
    registered = runtime._CUDA_DLL_DIRECTORIES
    handles.clear()
    registered.clear()
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path), raising=False)
    monkeypatch.setattr(runtime.os, 'add_dll_directory', lambda path: added.append(path) or object(), raising=False)

    runtime._add_frozen_cuda_library_directories()
    runtime._add_frozen_cuda_library_directories()

    assert set(added) == {str(cuda_dir), str(cudnn_dir)}
    assert len(handles) == len(registered) == 2
