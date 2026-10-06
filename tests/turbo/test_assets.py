import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from piper import turbo_assets as assets


EXPECTED_MODEL_SHA256 = {
    't3_turbo_v1.safetensors': 'fcf1f8c1d651bb7e3acd69ee5be269b4ac10c02980b7708213d598bc9f7cdf87',
    've.safetensors': 'f0921cab452fa278bc25cd23ffd59d36f816d7dc5181dd1bef9751a7fb61f63c',
    's3gen_meanflow.safetensors': 'd65cb687a2ed581ee6cc297e919ffefa63386944f42364ae13b78a594945514f',
    'conds.pt': 'b1852099306fd6a7814eb9d0bd10186caba7249596cc23868f78a0eefbfa5033',
    'tokenizer_config.json': 'bca16a2ac1ddbd78b8d6228f0031884cc74b6ea54b967d6f6d2ebae9ccde23e6',
    'special_tokens_map.json': '92ba8063bf40aa163eadebbfe0de07c2aebe44cf0d4a9e8726580b0781fd2640',
    'added_tokens.json': '72e4ab6acb0d9309ac3df4b526ae5fd80a2da5bc5ab7bb02d85096a374f69193',
    'vocab.json': 'f6bd25a65e4e63ca31360e9fb11c7e4f9a391a78385d640acd814092dd6eee4f',
    'merges.txt': '1ce1664773c50f3e0cc8842619a93edc4624525b728b188a9e0be33b7726adc5',
}


def _write_manifest(root, files, **overrides):
    manifest = {
        'manifest_version': 1,
        'engine': assets.ENGINE,
        'source_revision': assets.SOURCE_REVISION,
        'model_repo': assets.MODEL_REPO,
        'model_revision': assets.MODEL_REVISION,
        'files': files,
        **overrides,
    }
    (root / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')


def _make_payload(tmp_path, monkeypatch):
    root = tmp_path / 'turbo_payload'
    worker, model = root / 'worker', root / 'model'
    worker.mkdir(parents=True)
    model.mkdir()
    (worker / 'TurboWorker.exe').write_bytes(b'worker fixture')
    for name in assets.REQUIRED_MODEL_FILES:
        (model / name).write_bytes(('model fixture:' + name).encode('utf-8'))
    monkeypatch.setattr(assets, 'MODEL_FILE_SHA256', {
        name: assets.file_sha256(model / name) for name in assets.REQUIRED_MODEL_FILES
    })
    files = {
        path.relative_to(root).as_posix(): assets.file_sha256(path)
        for path in root.rglob('*') if path.is_file()
    }
    _write_manifest(root, files)
    return root, files


def test_turbo_pins_match_immutable_hugging_face_revision():
    assert assets.ENGINE == 'Chatterbox Turbo (350M)'
    assert assets.SOURCE_REVISION == '5de7a54aa4e5e2baadb0182dde554908b48b85c2'
    assert assets.MODEL_REPO == 'ResembleAI/chatterbox-turbo'
    assert assets.MODEL_REVISION == '749d1c1a46eb10492095d68fbcf55691ccf137cd'
    assert set(assets.REQUIRED_MODEL_FILES) == set(EXPECTED_MODEL_SHA256)
    assert assets.MODEL_FILE_SHA256 == EXPECTED_MODEL_SHA256


def test_inspects_complete_offline_turbo_installation(tmp_path, monkeypatch):
    root, _ = _make_payload(tmp_path, monkeypatch)

    installation = assets.inspect_turbo_installation(root)

    assert installation.root == root.resolve()
    assert installation.worker_executable == root.resolve() / 'worker' / 'TurboWorker.exe'
    assert installation.model_dir == root.resolve() / 'model'
    assert installation.manifest_sha256 == hashlib.sha256((root / 'manifest.json').read_bytes()).hexdigest()


def test_rejects_manifest_path_escape(tmp_path, monkeypatch):
    root, files = _make_payload(tmp_path, monkeypatch)
    files['../outside.bin'] = '0' * 64
    _write_manifest(root, files)

    with pytest.raises(ValueError, match='escapes root'):
        assets.inspect_turbo_installation(root)


def test_rejects_manifest_that_omits_required_turbo_checkpoint(tmp_path, monkeypatch):
    root, files = _make_payload(tmp_path, monkeypatch)
    del files['model/t3_turbo_v1.safetensors']
    _write_manifest(root, files)

    with pytest.raises(ValueError, match='required Turbo assets missing'):
        assets.inspect_turbo_installation(root)


def test_rejects_unmanifested_payload_file(tmp_path, monkeypatch):
    root, _ = _make_payload(tmp_path, monkeypatch)
    (root / 'model' / 'unexpected.bin').write_bytes(b'extra')

    with pytest.raises(ValueError, match='payload inventory differs from manifest'):
        assets.inspect_turbo_installation(root)


def test_rejects_tampered_pinned_model_even_when_manifest_is_rewritten(tmp_path, monkeypatch):
    root, files = _make_payload(tmp_path, monkeypatch)
    model_file = root / 'model' / 've.safetensors'
    model_file.write_bytes(b'tampered model')
    files['model/ve.safetensors'] = assets.file_sha256(model_file)
    _write_manifest(root, files)

    with pytest.raises(ValueError, match='pinned model hash mismatch: ve.safetensors'):
        assets.inspect_turbo_installation(root)


@pytest.mark.parametrize('field,value', [
    ('engine', 'Chatterbox Nano'),
    ('source_revision', '0' * 40),
    ('model_repo', 'ResembleAI/chatterbox-nano'),
    ('model_revision', '1' * 40),
])
def test_rejects_incompatible_turbo_manifest(tmp_path, monkeypatch, field, value):
    root, _ = _make_payload(tmp_path, monkeypatch)
    manifest_path = root / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest[field] = value
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')

    with pytest.raises(ValueError, match='unsupported Turbo manifest|incompatible Turbo revisions'):
        assets.inspect_turbo_installation(root)


def test_stager_copies_only_pinned_model_files_into_shared_payload(tmp_path, monkeypatch):
    source_model, worker = tmp_path / 'source_model', tmp_path / 'worker'
    source_model.mkdir()
    worker.mkdir()
    (worker / 'ChatterboxWorker.exe').write_bytes(b'worker fixture')
    for name in assets.REQUIRED_MODEL_FILES:
        (source_model / name).write_bytes(('model fixture:' + name).encode('utf-8'))
    monkeypatch.setattr(assets, 'MODEL_FILE_SHA256', {
        name: assets.file_sha256(source_model / name) for name in assets.REQUIRED_MODEL_FILES
    })

    script_path = Path(__file__).resolve().parents[2] / 'script' / 'stage_chatterbox_payload.py'
    spec = importlib.util.spec_from_file_location('stage_chatterbox_payload_under_test', script_path)
    stage_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stage_module)
    output = tmp_path / 'staged_turbo'
    monkeypatch.setattr(sys, 'argv', [
        'stage_chatterbox_payload.py', '--worker-dir', str(worker), '--turbo-model-dir', str(source_model),
        '--output', str(output),
    ])

    stage_module.main()

    from piper.chatterbox_assets import inspect_chatterbox_installation
    installation = inspect_chatterbox_installation(output, 'turbo')
    assert set(path.name for path in installation.model_dir.iterdir()) == set(assets.REQUIRED_MODEL_FILES)
    assert not list(installation.model_dir.rglob('*pkuseg*'))
    assert (installation.worker_executable).read_bytes() == b'worker fixture'


@pytest.mark.parametrize('contents', ['null', '[]', '"manifest"'])
def test_rejects_non_object_manifest_root(tmp_path, monkeypatch, contents):
    root, _ = _make_payload(tmp_path, monkeypatch)
    (root / 'manifest.json').write_text(contents, encoding='utf-8')

    with pytest.raises(ValueError, match='invalid Turbo manifest'):
        assets.inspect_turbo_installation(root)
