"""Verified, revision-pinned local Chatterbox Nano payloads."""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json

SOURCE_REVISION = '5de7a54aa4e5e2baadb0182dde554908b48b85c2'
MODEL_REVISION = '71ccd1d0081b430592cea481f4307e764e07bc64'
REQUIRED_MODEL_FILES = ('t3_nano_v1.safetensors', 've.safetensors', 's3gen_meanflow.safetensors', 'conds.pt', 'tokenizer_config.json', 'special_tokens_map.json', 'added_tokens.json', 'vocab.json', 'merges.txt')
MODEL_FILE_SHA256 = {
    'added_tokens.json': '72e4ab6acb0d9309ac3df4b526ae5fd80a2da5bc5ab7bb02d85096a374f69193',
    'conds.pt': 'b1852099306fd6a7814eb9d0bd10186caba7249596cc23868f78a0eefbfa5033',
    'merges.txt': '1ce1664773c50f3e0cc8842619a93edc4624525b728b188a9e0be33b7726adc5',
    's3gen_meanflow.safetensors': 'd65cb687a2ed581ee6cc297e919ffefa63386944f42364ae13b78a594945514f',
    'special_tokens_map.json': '92ba8063bf40aa163eadebbfe0de07c2aebe44cf0d4a9e8726580b0781fd2640',
    't3_nano_v1.safetensors': '72b110185087d945dbdf54dee4e333848e1811bdd5fd6cb16ceb8da50006f0c9',
    'tokenizer_config.json': 'bca16a2ac1ddbd78b8d6228f0031884cc74b6ea54b967d6f6d2ebae9ccde23e6',
    've.safetensors': 'f0921cab452fa278bc25cd23ffd59d36f816d7dc5181dd1bef9751a7fb61f63c',
    'vocab.json': 'f6bd25a65e4e63ca31360e9fb11c7e4f9a391a78385d640acd814092dd6eee4f',
}

@dataclass(frozen=True)
class NanoInstallation:
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


def inspect_nano_installation(root):
    root = Path(root).resolve()
    raw = (root / 'manifest.json').read_bytes()
    manifest = json.loads(raw)
    if manifest.get('manifest_version') != 1 or manifest.get('engine') != 'Chatterbox Nano':
        raise ValueError('unsupported Nano manifest')
    if manifest.get('source_revision') != SOURCE_REVISION or manifest.get('model_revision') != MODEL_REVISION:
        raise ValueError('incompatible Nano revisions')
    files = manifest.get('files')
    if not isinstance(files, dict) or not files:
        raise ValueError('Nano manifest has no files')
    normalized = set()
    for relative, expected in files.items():
        if not isinstance(relative, str):
            raise ValueError('invalid Nano asset path')
        path = (root / relative).resolve()
        if root not in path.parents:
            raise ValueError('Nano asset path escapes root')
        name = path.relative_to(root).as_posix()
        if name in normalized:
            raise ValueError('duplicate Nano asset path')
        normalized.add(name)
        if not path.is_file() or not isinstance(expected, str) or file_sha256(path) != expected:
            raise ValueError('Nano asset hash mismatch: ' + name)
    required = {'worker/NanoWorker.exe', *('model/' + name for name in REQUIRED_MODEL_FILES)}
    if not required <= normalized:
        raise ValueError('required Nano assets missing from manifest')
    for name, expected in MODEL_FILE_SHA256.items():
        if file_sha256(root / 'model' / name) != expected:
            raise ValueError('pinned model hash mismatch: ' + name)
    actual = {path.relative_to(root).as_posix() for path in root.rglob('*') if path.is_file() and path != root / 'manifest.json'}
    if normalized != actual:
        raise ValueError('Nano payload inventory differs from manifest')
    return NanoInstallation(root, root / 'worker/NanoWorker.exe', root / 'model', hashlib.sha256(raw).hexdigest())
