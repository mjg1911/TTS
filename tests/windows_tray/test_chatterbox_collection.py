"""Execute the tray collection recipe without freezing its dependencies."""
from pathlib import Path
import json
import sys
from types import ModuleType

import pytest

from tests.windows_tray.test_chatterbox_assets import _file_hash, _write_shared_payload


ROOT = Path(__file__).resolve().parents[2]


def _execute_tray_spec(monkeypatch, tmp_path, payload):
    fake_root = tmp_path / 'source'
    (fake_root / 'script').mkdir(parents=True)
    extensions = fake_root / 'src' / 'piper'
    extensions.mkdir(parents=True)
    (extensions / 'espeakbridge.pyd').touch()
    hooks = ModuleType('PyInstaller.utils.hooks')
    hooks.collect_data_files = lambda _name: []
    hooks.collect_dynamic_libs = lambda _name: []
    hooks.collect_submodules = lambda _name: []
    monkeypatch.setitem(sys.modules, 'PyInstaller.utils.hooks', hooks)
    monkeypatch.setenv('PIPER_CHATTERBOX_PAYLOAD_DIR', str(payload))
    monkeypatch.delenv('PIPER_NANO_PAYLOAD_DIR', raising=False)
    monkeypatch.delenv('PIPER_TURBO_PAYLOAD_DIR', raising=False)
    collected = []

    class Analysis:
        def __init__(self, _scripts, **options):
            collected.extend(options['datas'])
            self.pure, self.scripts, self.binaries, self.datas = [], [], [], options['datas']

    namespace = {
        'SPECPATH': str(fake_root / 'script'), 'Analysis': Analysis,
        'PYZ': lambda *args, **kwargs: None,
        'EXE': lambda *args, **kwargs: None,
        'COLLECT': lambda *args, **kwargs: None,
    }
    exec(compile((ROOT / 'script' / 'piper_tray.spec').read_text(), 'piper_tray.spec', 'exec'), namespace)
    return collected


def test_tray_collects_both_models_and_dependencies_in_one_runtime_tree(monkeypatch, tmp_path):
    payload, manifest, manifest_path = _write_shared_payload(tmp_path, monkeypatch)
    dependency = payload / 'worker' / '_internal' / 'torch.dll'
    dependency.parent.mkdir()
    dependency.write_bytes(b'shared dependency')
    manifest['files']['worker/_internal/torch.dll'] = _file_hash(dependency)
    manifest_path.write_text(json.dumps(manifest), encoding='utf8')
    monkeypatch.setenv('PIPER_REQUIRE_NANO_PAYLOAD', '1')
    monkeypatch.setenv('PIPER_REQUIRE_TURBO_PAYLOAD', '1')
    collected = _execute_tray_spec(monkeypatch, tmp_path, payload)
    worker_entries = [(source, destination) for source, destination in collected
                      if Path(source).name == 'ChatterboxWorker.exe']
    assert len(worker_entries) == 1
    assert Path(worker_entries[0][1]).as_posix() == 'chatterbox_payload/worker'
    sources = [Path(source) for source, _ in collected]
    assert sources.count(dependency) == 1
    assert payload / 'models' / 'nano' / 't3_nano_v1.safetensors' in sources
    assert payload / 'models' / 'turbo' / 't3_turbo_v1.safetensors' in sources
    assert all('nano_payload' not in destination and 'turbo_payload' not in destination
               for _, destination in collected)


def test_tray_rejects_required_engine_missing_from_shared_payload(monkeypatch, tmp_path):
    payload, _, _ = _write_shared_payload(tmp_path, monkeypatch, engines=('nano',))
    monkeypatch.setenv('PIPER_REQUIRE_NANO_PAYLOAD', '1')
    monkeypatch.setenv('PIPER_REQUIRE_TURBO_PAYLOAD', '1')
    with pytest.raises((ValueError, RuntimeError), match='absent|Turbo|turbo'):
        _execute_tray_spec(monkeypatch, tmp_path, payload)


def test_tray_rejects_invalid_payload_even_without_required_engine_flags(monkeypatch, tmp_path):
    payload, manifest, manifest_path = _write_shared_payload(tmp_path, monkeypatch)
    manifest['models'] = {}
    manifest_path.write_text(json.dumps(manifest), encoding='utf8')
    monkeypatch.delenv('PIPER_REQUIRE_NANO_PAYLOAD', raising=False)
    monkeypatch.delenv('PIPER_REQUIRE_TURBO_PAYLOAD', raising=False)
    with pytest.raises((ValueError, RuntimeError), match='model|manifest|engine'):
        _execute_tray_spec(monkeypatch, tmp_path, payload)
