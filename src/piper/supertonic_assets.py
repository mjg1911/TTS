"""Validate a revision-pinned, offline Supertonic 3 installation."""

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from os.path import commonpath

from piper.supertonic_options import ENGINE, VOICES


MODEL_REPO = 'Supertone/supertonic-3'
MODEL_REVISION = '3cadd1ee6394adea1bd021217a0e650ede09a323'
SOURCE_REPO = 'supertone-oss-archive/supertonic-py'
SOURCE_REVISION = 'df0f9686dac7fbbde391b759e2ee5286a3737622'
MANIFEST_NAME = 'model_assets.json'
WORKER_RELATIVE_PATH = 'worker/SupertonicWorker.exe'

REQUIRED_MODEL_FILES = (
    'config.json',
    'LICENSE',
    'SOURCE-LICENSE',
    'onnx/tts.json',
    'onnx/unicode_indexer.json',
    'onnx/duration_predictor.onnx',
    'onnx/text_encoder.onnx',
    'onnx/vector_estimator.onnx',
    'onnx/vocoder.onnx',
    *(f'voice_styles/{voice}.json' for voice, _label in VOICES),
)
REQUIRED_FILES = (*REQUIRED_MODEL_FILES, WORKER_RELATIVE_PATH)


@dataclass(frozen=True)
class Supertonic3Installation:
    root: Path
    worker_executable: Path
    model_dir: Path
    manifest_sha256: str


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _has_development_worker():
    python = os.environ.get('PIPER_SUPERTONIC_WORKER_PYTHON')
    return bool(python and Path(python).expanduser().is_file())


def inspect_supertonic3_installation(root):
    """Return a verified install descriptor or explain why it is unusable."""
    try:
        root = Path(os.path.abspath(Path(root).expanduser()))
        if not root.is_dir() or root.is_symlink():
            raise ValueError('installation root is not a regular directory')
        manifest_path = root / MANIFEST_NAME
        if manifest_path.is_symlink():
            raise ValueError('manifest must not be a symbolic link')
        raw_manifest = manifest_path.read_bytes()
        manifest = json.loads(raw_manifest)
    except (OSError, RuntimeError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError('invalid Supertonic 3 installation manifest') from error

    if not isinstance(manifest, dict):
        raise ValueError('invalid Supertonic 3 installation manifest')
    if manifest.get('manifest_version') != 1 or manifest.get('engine') != ENGINE:
        raise ValueError('unsupported Supertonic 3 manifest')
    if (manifest.get('model_repo') != MODEL_REPO
            or manifest.get('model_revision') != MODEL_REVISION
            or manifest.get('source_repo') != SOURCE_REPO
            or manifest.get('source_revision') != SOURCE_REVISION):
        raise ValueError('incompatible Supertonic 3 revisions')

    files = manifest.get('files')
    if not isinstance(files, dict) or not files:
        raise ValueError('Supertonic 3 manifest has no files')

    normalized = set()
    for relative, expected in files.items():
        if not isinstance(relative, str) or not relative:
            raise ValueError('invalid Supertonic 3 asset path')
        path = Path(os.path.abspath(root / relative))
        try:
            if commonpath((str(root), str(path))) != str(root):
                raise ValueError('Supertonic 3 asset path escapes root')
        except ValueError as error:
            raise ValueError('Supertonic 3 asset path escapes root') from error
        if path == root:
            raise ValueError('Supertonic 3 asset path escapes root')
        name = path.relative_to(root).as_posix()
        if name == MANIFEST_NAME or name in normalized:
            raise ValueError('duplicate Supertonic 3 asset path')
        normalized.add(name)
        cursor = path
        while cursor != root:
            if cursor.is_symlink():
                raise ValueError('Supertonic 3 asset path must not be a symbolic link: ' + name)
            cursor = cursor.parent
        if (not isinstance(expected, str) or len(expected) != 64
                or any(char not in '0123456789abcdef' for char in expected)):
            raise ValueError('invalid Supertonic 3 asset hash: ' + name)
        if not path.is_file() or file_sha256(path) != expected:
            raise ValueError('Supertonic 3 asset hash mismatch: ' + name)

    has_development_worker = _has_development_worker()
    if WORKER_RELATIVE_PATH not in normalized and not has_development_worker:
        raise ValueError(
            'Supertonic 3 worker executable is missing and '
            'PIPER_SUPERTONIC_WORKER_PYTHON is not available'
        )

    required = set(REQUIRED_FILES)
    if has_development_worker:
        required.discard(WORKER_RELATIVE_PATH)
    if not required <= normalized:
        raise ValueError('required Supertonic assets missing from manifest')

    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob('*')
        if path.is_file() and path != manifest_path
    }
    if normalized != actual:
        raise ValueError('Supertonic 3 payload inventory differs from manifest')

    return Supertonic3Installation(
        root=root,
        worker_executable=root / WORKER_RELATIVE_PATH,
        model_dir=root,
        manifest_sha256=hashlib.sha256(raw_manifest).hexdigest(),
    )


def inspect_supertonic_installation(root):
    """Compatibility spelling used by the tray integration."""
    return inspect_supertonic3_installation(root)
