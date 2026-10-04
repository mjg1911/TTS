import importlib
import io
from types import SimpleNamespace
from piper.windows_tray.worker_protocol import write_frame, read_frame, decode_audio


def test_worker_transmits_gpu_failure(monkeypatch, tmp_path):
    module = importlib.import_module('piper.multilingual_worker.main')
    monkeypatch.setattr(module, 'inspect_multilingual_installation', lambda _: SimpleNamespace(root=tmp_path, model_dir=tmp_path, manifest_sha256='a'*64))
    monkeypatch.setattr(module, '_configure_numba_cache', lambda _: None)
    def unavailable(*args, **kwargs):
        raise RuntimeError('NVIDIA GPU with CUDA is required.')
    monkeypatch.setattr(module, 'load_model', unavailable)
    incoming, outgoing = io.BytesIO(), io.BytesIO()
    write_frame(incoming, {'type':'initialize','manifest_sha256':'a'*64,'device':'cuda','language':'en','exaggeration':0.5,'cfg_weight':0.5})
    incoming.seek(0)
    module.serve(tmp_path, incoming, outgoing)
    outgoing.seek(0)
    assert read_frame(outgoing)['type'] == 'hello'
    assert read_frame(outgoing) == {'type':'startup_error','message':'NVIDIA GPU with CUDA is required.'}


def test_worker_generates_framed_audio_with_configured_options(monkeypatch, tmp_path):
    module = importlib.import_module('piper.multilingual_worker.main')
    monkeypatch.setattr(module, 'inspect_multilingual_installation', lambda _: SimpleNamespace(root=tmp_path, model_dir=tmp_path, manifest_sha256='a'*64))
    monkeypatch.setattr(module, '_configure_numba_cache', lambda _: None)
    loaded, generated = [], []
    model = SimpleNamespace(sr=24000)
    monkeypatch.setattr(module, 'load_model', lambda *a, **k: loaded.append(k) or model)
    monkeypatch.setattr(module, 'generate_chunks', lambda *a: generated.append(a) or iter([b'\x01\x00']))
    incoming, outgoing = io.BytesIO(), io.BytesIO()
    write_frame(incoming, {'type':'initialize','manifest_sha256':'a'*64,'device':'cuda','language':'nl','exaggeration':0.8,'cfg_weight':0.3})
    write_frame(incoming, {'type':'synthesize','request_id':1,'text':'Goedemorgen.','voice_id':'default'})
    incoming.seek(0)
    module.serve(tmp_path, incoming, outgoing)
    outgoing.seek(0)
    assert read_frame(outgoing)['engine'] == 'Chatterbox Multilingual V3 (500M)'
    assert read_frame(outgoing)['device'] == 'cuda'
    assert decode_audio(read_frame(outgoing)['audio']) == b'\x01\x00'
    assert read_frame(outgoing) == {'type':'response_end','request_id':1}
    assert loaded == [{'reference_clip':None, 'exaggeration':0.8}]
    assert generated == [(model, 'Goedemorgen.', 'nl', 0.8, 0.3)]
