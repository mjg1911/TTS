import hashlib
import json
from pathlib import Path

import pytest

from piper import supertonic_assets as assets


def _write_manifest(root, files, **overrides):
    manifest = {
        'manifest_version': 1,
        'engine': assets.ENGINE,
        'model_repo': assets.MODEL_REPO,
        'model_revision': assets.MODEL_REVISION,
        'source_repo': assets.SOURCE_REPO,
        'source_revision': assets.SOURCE_REVISION,
        'files': files,
        **overrides,
    }
    (root / assets.MANIFEST_NAME).write_text(json.dumps(manifest), encoding='utf-8')


def _make_payload(tmp_path, monkeypatch):
    root = tmp_path / 'Supertonic3'
    root.mkdir()
    for relative in assets.REQUIRED_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(('fixture:' + relative).encode())
    files = {
        path.relative_to(root).as_posix(): assets.file_sha256(path)
        for path in root.rglob('*') if path.is_file()
    }
    _write_manifest(root, files)
    return root, files


def test_official_archive_revisions_and_required_sdk_payload_are_pinned():
    assert assets.ENGINE == 'Supertonic 3'
    assert assets.MODEL_REPO == 'Supertone/supertonic-3'
    assert assets.MODEL_REVISION == '3cadd1ee6394adea1bd021217a0e650ede09a323'
    assert assets.SOURCE_REPO == 'supertone-oss-archive/supertonic-py'
    assert assets.SOURCE_REVISION == 'df0f9686dac7fbbde391b759e2ee5286a3737622'
    assert {
        'onnx/tts.json', 'onnx/unicode_indexer.json',
        'onnx/duration_predictor.onnx', 'onnx/text_encoder.onnx',
        'onnx/vector_estimator.onnx', 'onnx/vocoder.onnx',
        'voice_styles/M1.json', 'voice_styles/F5.json',
    } <= set(assets.REQUIRED_FILES)


def test_inspects_complete_offline_installation(tmp_path, monkeypatch):
    root, _ = _make_payload(tmp_path, monkeypatch)

    installation = assets.inspect_supertonic3_installation(root)

    assert installation.root == root.resolve()
    assert installation.model_dir == root.resolve()
    assert installation.worker_executable == root.resolve() / 'worker' / 'SupertonicWorker.exe'
    assert installation.manifest_sha256 == hashlib.sha256(
        (root / assets.MANIFEST_NAME).read_bytes()
    ).hexdigest()


def test_rejects_manifest_path_escape(tmp_path, monkeypatch):
    root, files = _make_payload(tmp_path, monkeypatch)
    files['../outside.bin'] = '0' * 64
    _write_manifest(root, files)

    with pytest.raises(ValueError, match='escapes root'):
        assets.inspect_supertonic3_installation(root)


def test_rejects_missing_required_checkpoint(tmp_path, monkeypatch):
    root, files = _make_payload(tmp_path, monkeypatch)
    del files['onnx/vocoder.onnx']
    _write_manifest(root, files)

    with pytest.raises(ValueError, match='required Supertonic assets missing'):
        assets.inspect_supertonic3_installation(root)


def test_rejects_tampered_asset(tmp_path, monkeypatch):
    root, _ = _make_payload(tmp_path, monkeypatch)
    (root / 'onnx' / 'vocoder.onnx').write_bytes(b'tampered')

    with pytest.raises(ValueError, match='asset hash mismatch'):
        assets.inspect_supertonic3_installation(root)


def test_rejects_unmanifested_payload_file(tmp_path, monkeypatch):
    root, _ = _make_payload(tmp_path, monkeypatch)
    (root / 'unexpected.bin').write_bytes(b'extra')

    with pytest.raises(ValueError, match='payload inventory differs from manifest'):
        assets.inspect_supertonic3_installation(root)


def test_dev_mode_requires_an_existing_worker_python(tmp_path, monkeypatch):
    root, files = _make_payload(tmp_path, monkeypatch)
    worker = root / 'worker' / 'SupertonicWorker.exe'
    worker.unlink()
    files.pop('worker/SupertonicWorker.exe')
    _write_manifest(root, files)
    python = tmp_path / 'python.exe'
    python.write_bytes(b'python fixture')
    monkeypatch.setenv('PIPER_SUPERTONIC_WORKER_PYTHON', str(python))

    assert assets.inspect_supertonic3_installation(root).worker_executable == worker

    monkeypatch.setenv('PIPER_SUPERTONIC_WORKER_PYTHON', str(tmp_path / 'missing.exe'))
    with pytest.raises(ValueError, match='worker executable'):
        assets.inspect_supertonic3_installation(root)

