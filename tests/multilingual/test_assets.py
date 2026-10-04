import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import zipfile

import pytest

from piper import multilingual_assets


EXPECTED_MODEL_SHA256 = {
    've.pt': '4b16d836bc598509860f6fa068165a8bb5e9ac84f05582dfcf278a5a372879f1',
    't3_mtl23ls_v3.safetensors': '5abca8321ede76f8e61f1cc0d19aea6c946b28871017ce8726f8a69203f05953',
    's3gen.pt': '9b9ff07e60b20c136e2b1b3d7563a24604e8d2c4c267888d1ee929dd0151d2a3',
    'grapheme_mtl_merged_expanded_v1.json': '69632f47220a788a52ce2661d096453c5655e9bf25289d89a8d832c46ee07dbf',
    'conds.pt': '6552d70568833628ba019c6b03459e77fe71ca197d5c560cef9411bee9d87f4e',
    'Cangjie5_TC.json': '7073fd9de919443ae88e0bd2449917a65fe54898a4413ed1edcc4b67f28bce8c',
}
EXPECTED_MODEL_GIT_SHA1 = {
    'grapheme_mtl_merged_expanded_v1.json': 'd27fb3f2fd38ca39b7bbfbf83a13b3c617e551df',
    'Cangjie5_TC.json': 'd77891f84ca1db0d6f7058a4ee081d4bb0bfe88e',
}
EXPECTED_PKUSEG_ARCHIVE_SHA256 = 'b216e7f92de7ae285aeab8feba2faa8ea8216e5995ff6fb3d391cc8356db1bfe'
EXPECTED_PKUSEG_FILE_SHA256 = {
    'features.msgpack': 'fd4322482a7018b9bce9216173ae9d2848efe6d310b468bbb4383fb55c874a18',
    'weights.npz': '5ada075eb25a854f71d6e6fa4e7d55e7be0ae049255b1f8f19d05c13b1b68c9e',
}


def _cache_snapshot_path():
    return Path('models--ResembleAI--chatterbox') / 'snapshots' / multilingual_assets.MODEL_REVISION / 'Cangjie5_TC.json'


def _write_manifest(root, files):
    manifest = {
        'manifest_version': 1,
        'engine': multilingual_assets.ENGINE,
        'source_revision': multilingual_assets.SOURCE_REVISION,
        'model_repo': multilingual_assets.MODEL_REPO,
        'model_revision': multilingual_assets.MODEL_REVISION,
        'files': files,
    }
    (root / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')


def _make_payload(tmp_path, monkeypatch):
    root = tmp_path / 'multilingual_payload'
    worker = root / 'worker'
    model = root / 'model'
    worker.mkdir(parents=True)
    model.mkdir()
    (worker / 'MultilingualWorker.exe').write_bytes(b'worker fixture')

    for name in multilingual_assets.REQUIRED_MODEL_FILES:
        (model / name).write_bytes(('model fixture:' + name).encode('utf-8'))

    cache_copy = model / _cache_snapshot_path()
    cache_copy.parent.mkdir(parents=True)
    cache_copy.write_bytes((model / 'Cangjie5_TC.json').read_bytes())
    refs = model / 'models--ResembleAI--chatterbox' / 'refs' / 'main'
    refs.parent.mkdir(parents=True)
    refs.write_text(multilingual_assets.MODEL_REVISION, encoding='utf-8')

    pkuseg_root = model / 'pkuseg' / 'spacy_ontonotes'
    pkuseg_root.mkdir(parents=True)
    archive = model / 'pkuseg' / 'spacy_ontonotes.zip'
    archive.write_bytes(b'pkuseg archive fixture')
    for name in EXPECTED_PKUSEG_FILE_SHA256:
        (pkuseg_root / name).write_bytes(('pkuseg fixture:' + name).encode('utf-8'))

    pinned_hashes = {
        name: multilingual_assets.file_sha256(model / name)
        for name in multilingual_assets.REQUIRED_MODEL_FILES
    }
    monkeypatch.setattr(multilingual_assets, 'MODEL_FILE_SHA256', pinned_hashes)
    monkeypatch.setattr(multilingual_assets, 'MODEL_FILE_GIT_SHA1', {
        name: multilingual_assets.git_blob_sha1(model / name)
        for name in EXPECTED_MODEL_GIT_SHA1
    })
    monkeypatch.setattr(multilingual_assets, 'PKUSEG_ARCHIVE_SHA256', multilingual_assets.file_sha256(archive))
    monkeypatch.setattr(multilingual_assets, 'PKUSEG_FILE_SHA256', {
        name: multilingual_assets.file_sha256(pkuseg_root / name)
        for name in EXPECTED_PKUSEG_FILE_SHA256
    })
    files = {
        path.relative_to(root).as_posix(): multilingual_assets.file_sha256(path)
        for path in root.rglob('*')
        if path.is_file()
    }
    _write_manifest(root, files)
    return root, files


def test_multilingual_asset_pins_match_hugging_face_metadata():
    assert multilingual_assets.ENGINE == 'Chatterbox Multilingual V3 (500M)'
    assert multilingual_assets.SOURCE_REVISION == '5de7a54aa4e5e2baadb0182dde554908b48b85c2'
    assert multilingual_assets.MODEL_REVISION == '5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18'
    assert set(multilingual_assets.REQUIRED_MODEL_FILES) == set(EXPECTED_MODEL_SHA256)
    assert multilingual_assets.MODEL_FILE_SHA256 == EXPECTED_MODEL_SHA256
    assert multilingual_assets.MODEL_FILE_GIT_SHA1 == EXPECTED_MODEL_GIT_SHA1
    assert multilingual_assets.PKUSEG_ARCHIVE_SHA256 == EXPECTED_PKUSEG_ARCHIVE_SHA256
    assert multilingual_assets.PKUSEG_FILE_SHA256 == EXPECTED_PKUSEG_FILE_SHA256


def test_inspects_complete_offline_multilingual_installation(tmp_path, monkeypatch):
    root, _ = _make_payload(tmp_path, monkeypatch)

    installation = multilingual_assets.inspect_multilingual_installation(root)

    assert installation.root == root.resolve()
    assert installation.worker_executable == root.resolve() / 'worker' / 'MultilingualWorker.exe'
    assert installation.model_dir == root.resolve() / 'model'
    assert installation.manifest_sha256 == hashlib.sha256((root / 'manifest.json').read_bytes()).hexdigest()


def test_rejects_manifest_path_escape(tmp_path, monkeypatch):
    root, files = _make_payload(tmp_path, monkeypatch)
    files['../outside.bin'] = '0' * 64
    _write_manifest(root, files)

    with pytest.raises(ValueError, match='escapes root'):
        multilingual_assets.inspect_multilingual_installation(root)


def test_rejects_manifest_inventory_that_omits_required_model_asset(tmp_path, monkeypatch):
    root, files = _make_payload(tmp_path, monkeypatch)
    del files['model/t3_mtl23ls_v3.safetensors']
    _write_manifest(root, files)

    with pytest.raises(ValueError, match='required multilingual assets missing'):
        multilingual_assets.inspect_multilingual_installation(root)


def test_rejects_unmanifested_payload_file(tmp_path, monkeypatch):
    root, _ = _make_payload(tmp_path, monkeypatch)
    (root / 'model' / 'unexpected.bin').write_bytes(b'extra')

    with pytest.raises(ValueError, match='payload inventory differs from manifest'):
        multilingual_assets.inspect_multilingual_installation(root)


def test_rejects_changed_pinned_model_file_even_if_manifest_is_rewritten(tmp_path, monkeypatch):
    root, files = _make_payload(tmp_path, monkeypatch)
    model_file = root / 'model' / 've.pt'
    model_file.write_bytes(b'tampered model')
    files['model/ve.pt'] = multilingual_assets.file_sha256(model_file)
    _write_manifest(root, files)

    with pytest.raises(ValueError, match='pinned model hash mismatch: ve.pt'):
        multilingual_assets.inspect_multilingual_installation(root)


@pytest.mark.parametrize('relative', [
    Path('pkuseg') / 'spacy_ontonotes.zip',
    Path('pkuseg') / 'spacy_ontonotes' / 'features.msgpack',
    Path('pkuseg') / 'spacy_ontonotes' / 'weights.npz',
])
def test_rejects_changed_pkuseg_asset_even_if_manifest_is_rewritten(tmp_path, monkeypatch, relative):
    root, files = _make_payload(tmp_path, monkeypatch)
    asset = root / 'model' / relative
    asset.write_bytes(b'tampered pkuseg model')
    files[(Path('model') / relative).as_posix()] = multilingual_assets.file_sha256(asset)
    _write_manifest(root, files)

    with pytest.raises(ValueError, match='pinned pkuseg hash mismatch'):
        multilingual_assets.inspect_multilingual_installation(root)


@pytest.mark.parametrize('relative,contents', [
    (_cache_snapshot_path(), b'changed cangjie cache'),
    (Path('models--ResembleAI--chatterbox') / 'refs' / 'main', b'wrong-revision'),
])
def test_rejects_inconsistent_hugging_face_offline_cache(tmp_path, monkeypatch, relative, contents):
    root, files = _make_payload(tmp_path, monkeypatch)
    cache_file = root / 'model' / relative
    cache_file.write_bytes(contents)
    files[(Path('model') / relative).as_posix()] = multilingual_assets.file_sha256(cache_file)
    _write_manifest(root, files)

    with pytest.raises(ValueError, match='Hugging Face offline cache'):
        multilingual_assets.inspect_multilingual_installation(root)


@pytest.mark.parametrize('field,value', [
    ('engine', 'Chatterbox Nano'),
    ('source_revision', '0' * 40),
    ('model_repo', 'ResembleAI/chatterbox-nano'),
    ('model_revision', '1' * 40),
])
def test_rejects_incompatible_multilingual_manifest(tmp_path, monkeypatch, field, value):
    root, _ = _make_payload(tmp_path, monkeypatch)
    manifest_path = root / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest[field] = value
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')

    with pytest.raises(ValueError, match='unsupported Multilingual manifest|incompatible Multilingual revisions'):
        multilingual_assets.inspect_multilingual_installation(root)


def test_stager_builds_a_fully_offline_payload_from_local_inputs(tmp_path, monkeypatch):
    source_model = tmp_path / 'source_model'
    worker = tmp_path / 'worker'
    source_model.mkdir()
    worker.mkdir()
    (worker / 'MultilingualWorker.exe').write_bytes(b'worker fixture')
    for name in multilingual_assets.REQUIRED_MODEL_FILES:
        (source_model / name).write_bytes(('model fixture:' + name).encode('utf-8'))

    archive_source = tmp_path / 'spacy_ontonotes.zip'
    pkuseg_files = {
        'features.msgpack': b'pkuseg features',
        'weights.npz': b'pkuseg weights',
    }
    with zipfile.ZipFile(archive_source, 'w') as archive:
        for name, contents in pkuseg_files.items():
            archive.writestr(name, contents)
    monkeypatch.setattr(multilingual_assets, 'MODEL_FILE_SHA256', {
        name: multilingual_assets.file_sha256(source_model / name)
        for name in multilingual_assets.REQUIRED_MODEL_FILES
    })
    monkeypatch.setattr(multilingual_assets, 'MODEL_FILE_GIT_SHA1', {
        name: multilingual_assets.git_blob_sha1(source_model / name)
        for name in EXPECTED_MODEL_GIT_SHA1
    })
    monkeypatch.setattr(multilingual_assets, 'PKUSEG_ARCHIVE_SHA256', multilingual_assets.file_sha256(archive_source))
    monkeypatch.setattr(multilingual_assets, 'PKUSEG_FILE_SHA256', {
        name: hashlib.sha256(contents).hexdigest()
        for name, contents in pkuseg_files.items()
    })

    script_path = Path(__file__).resolve().parents[2] / 'script' / 'stage_multilingual_payload.py'
    spec = importlib.util.spec_from_file_location('stage_multilingual_payload_under_test', script_path)
    stage_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stage_module)
    output = tmp_path / 'multilingual_payload'
    monkeypatch.setattr(sys, 'argv', [
        'stage_multilingual_payload.py',
        '--worker-dir', str(worker),
        '--model-dir', str(source_model),
        '--pkuseg-archive', str(archive_source),
        '--output', str(output),
    ])

    stage_module.main()

    installation = multilingual_assets.inspect_multilingual_installation(output)
    assert (installation.model_dir / _cache_snapshot_path()).is_file()
    assert (installation.model_dir / 'models--ResembleAI--chatterbox' / 'refs' / 'main').read_text(encoding='utf-8') == multilingual_assets.MODEL_REVISION
    for name, contents in pkuseg_files.items():
        assert (installation.model_dir / 'pkuseg' / 'spacy_ontonotes' / name).read_bytes() == contents


@pytest.mark.parametrize('contents', ['null', '[]', '"manifest"'])
def test_rejects_non_object_manifest_root(tmp_path, monkeypatch, contents):
    root, _ = _make_payload(tmp_path, monkeypatch)
    (root / 'manifest.json').write_text(contents, encoding='utf-8')

    with pytest.raises(ValueError, match='invalid Multilingual manifest'):
        multilingual_assets.inspect_multilingual_installation(root)
