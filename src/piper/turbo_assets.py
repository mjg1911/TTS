"""Verify revision-pinned, offline Chatterbox Turbo worker installations."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from piper.turbo_options import ENGINE


SOURCE_REVISION = '5de7a54aa4e5e2baadb0182dde554908b48b85c2'
MODEL_REPO = 'ResembleAI/chatterbox-turbo'
# Hugging Face Hub API: /api/models/ResembleAI/chatterbox-turbo/commits/main
MODEL_REVISION = '749d1c1a46eb10492095d68fbcf55691ccf137cd'
REQUIRED_MODEL_FILES = (
    't3_turbo_v1.safetensors',
    've.safetensors',
    's3gen_meanflow.safetensors',
    'conds.pt',
    'tokenizer_config.json',
    'special_tokens_map.json',
    'added_tokens.json',
    'vocab.json',
    'merges.txt',
)

# Xet SHA-256 values come from the Hub API's file metadata at MODEL_REVISION.
# The remaining small tokenizer files were fetched from that revision and hashed.
MODEL_FILE_SHA256 = {
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


@dataclass(frozen=True)
class TurboInstallation:
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


def inspect_turbo_installation(root):
    root = Path(root).resolve()
    raw_manifest = (root / 'manifest.json').read_bytes()
    try:
        manifest = json.loads(raw_manifest)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError('invalid Turbo manifest') from error
    if not isinstance(manifest, dict):
        raise ValueError('invalid Turbo manifest')
    if manifest.get('manifest_version') != 1 or manifest.get('engine') != ENGINE:
        raise ValueError('unsupported Turbo manifest')
    if (manifest.get('source_revision') != SOURCE_REVISION
            or manifest.get('model_repo') != MODEL_REPO
            or manifest.get('model_revision') != MODEL_REVISION):
        raise ValueError('incompatible Turbo revisions')

    files = manifest.get('files')
    if not isinstance(files, dict) or not files:
        raise ValueError('Turbo manifest has no files')
    normalized = set()
    for relative, expected in files.items():
        if not isinstance(relative, str):
            raise ValueError('invalid Turbo asset path')
        path = (root / relative).resolve()
        if root not in path.parents:
            raise ValueError('Turbo asset path escapes root')
        name = path.relative_to(root).as_posix()
        if name in normalized:
            raise ValueError('duplicate Turbo asset path')
        normalized.add(name)
        if not path.is_file() or not isinstance(expected, str) or file_sha256(path) != expected:
            raise ValueError('Turbo asset hash mismatch: ' + name)

    required = {
        'worker/TurboWorker.exe',
        *(f'model/{name}' for name in REQUIRED_MODEL_FILES),
    }
    if not required <= normalized:
        raise ValueError('required Turbo assets missing from manifest')

    if set(MODEL_FILE_SHA256) != set(REQUIRED_MODEL_FILES):
        raise ValueError('Turbo model pin inventory is incomplete')
    for name, expected in MODEL_FILE_SHA256.items():
        if file_sha256(root / 'model' / name) != expected:
            raise ValueError('pinned model hash mismatch: ' + name)

    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob('*')
        if path.is_file() and path != root / 'manifest.json'
    }
    if normalized != actual:
        raise ValueError('Turbo payload inventory differs from manifest')

    return TurboInstallation(
        root,
        root / 'worker/TurboWorker.exe',
        root / 'model',
        hashlib.sha256(raw_manifest).hexdigest(),
    )
