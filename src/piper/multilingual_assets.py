"""Verify the pinned, offline Chatterbox Multilingual V3 installation."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path


ENGINE = 'Chatterbox Multilingual V3 (500M)'
SOURCE_REVISION = '5de7a54aa4e5e2baadb0182dde554908b48b85c2'
MODEL_REPO = 'ResembleAI/chatterbox'
MODEL_REVISION = '5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18'
REQUIRED_MODEL_FILES = (
    've.pt',
    't3_mtl23ls_v3.safetensors',
    's3gen.pt',
    'grapheme_mtl_merged_expanded_v1.json',
    'conds.pt',
    'Cangjie5_TC.json',
)

# SHA-256 values are the file hashes reported by the Hugging Face Hub API for
# Xet-backed files. The JSON hashes were calculated from files fetched at the
# immutable MODEL_REVISION above; the API's regular Git blob IDs are SHA-1.
MODEL_FILE_SHA256 = {
    've.pt': '4b16d836bc598509860f6fa068165a8bb5e9ac84f05582dfcf278a5a372879f1',
    't3_mtl23ls_v3.safetensors': '5abca8321ede76f8e61f1cc0d19aea6c946b28871017ce8726f8a69203f05953',
    's3gen.pt': '9b9ff07e60b20c136e2b1b3d7563a24604e8d2c4c267888d1ee929dd0151d2a3',
    'grapheme_mtl_merged_expanded_v1.json': '69632f47220a788a52ce2661d096453c5655e9bf25289d89a8d832c46ee07dbf',
    'conds.pt': '6552d70568833628ba019c6b03459e77fe71ca197d5c560cef9411bee9d87f4e',
    'Cangjie5_TC.json': '7073fd9de919443ae88e0bd2449917a65fe54898a4413ed1edcc4b67f28bce8c',
}
MODEL_FILE_GIT_SHA1 = {
    'grapheme_mtl_merged_expanded_v1.json': 'd27fb3f2fd38ca39b7bbfbf83a13b3c617e551df',
    'Cangjie5_TC.json': 'd77891f84ca1db0d6f7058a4ee081d4bb0bfe88e',
}

# Chatterbox's Chinese tokenizer uses Hugging Face's local cache lookup for
# Cangjie, and spacy-pkuseg downloads its default segmenter unless both its
# archive and extracted directory are already present.
HF_CACHE_CANGJIE = (
    f'models--{MODEL_REPO.replace("/", "--")}/snapshots/{MODEL_REVISION}/Cangjie5_TC.json'
)
HF_CACHE_MAIN_REF = f'models--{MODEL_REPO.replace("/", "--")}/refs/main'
PKUSEG_MODEL_URL = (
    'https://github.com/explosion/spacy-pkuseg/releases/download/'
    'v0.0.26/spacy_ontonotes.zip'
)
PKUSEG_ARCHIVE_SHA256 = 'b216e7f92de7ae285aeab8feba2faa8ea8216e5995ff6fb3d391cc8356db1bfe'
PKUSEG_FILE_SHA256 = {
    'features.msgpack': 'fd4322482a7018b9bce9216173ae9d2848efe6d310b468bbb4383fb55c874a18',
    'weights.npz': '5ada075eb25a854f71d6e6fa4e7d55e7be0ae049255b1f8f19d05c13b1b68c9e',
}
PKUSEG_MODEL_FILES = tuple(PKUSEG_FILE_SHA256)


@dataclass(frozen=True)
class MultilingualInstallation:
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


def git_blob_sha1(path):
    path = Path(path)
    size = path.stat().st_size
    digest = hashlib.sha1()
    digest.update(b'blob ' + str(size).encode('ascii') + b'\0')
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def inspect_multilingual_installation(root):
    root = Path(root).resolve()
    raw_manifest = (root / 'manifest.json').read_bytes()
    manifest = json.loads(raw_manifest)
    if not isinstance(manifest, dict):
        raise ValueError('invalid Multilingual manifest')
    if manifest.get('manifest_version') != 1 or manifest.get('engine') != ENGINE:
        raise ValueError('unsupported Multilingual manifest')
    if (manifest.get('source_revision') != SOURCE_REVISION or
            manifest.get('model_repo') != MODEL_REPO or
            manifest.get('model_revision') != MODEL_REVISION):
        raise ValueError('incompatible Multilingual revisions')

    files = manifest.get('files')
    if not isinstance(files, dict) or not files:
        raise ValueError('Multilingual manifest has no files')
    normalized = set()
    for relative, expected in files.items():
        if not isinstance(relative, str):
            raise ValueError('invalid Multilingual asset path')
        path = (root / relative).resolve()
        if root not in path.parents:
            raise ValueError('Multilingual asset path escapes root')
        name = path.relative_to(root).as_posix()
        if name in normalized:
            raise ValueError('duplicate Multilingual asset path')
        normalized.add(name)
        if not path.is_file() or not isinstance(expected, str) or file_sha256(path) != expected:
            raise ValueError('Multilingual asset hash mismatch: ' + name)

    required = {
        'worker/MultilingualWorker.exe',
        *(f'model/{name}' for name in REQUIRED_MODEL_FILES),
        f'model/{HF_CACHE_CANGJIE}',
        f'model/{HF_CACHE_MAIN_REF}',
        'model/pkuseg/spacy_ontonotes.zip',
        *(f'model/pkuseg/spacy_ontonotes/{name}' for name in PKUSEG_MODEL_FILES),
    }
    if not required <= normalized:
        raise ValueError('required multilingual assets missing from manifest')

    if set(MODEL_FILE_SHA256) != set(REQUIRED_MODEL_FILES):
        raise ValueError('Multilingual model pin inventory is incomplete')
    for name, expected in MODEL_FILE_SHA256.items():
        if file_sha256(root / 'model' / name) != expected:
            raise ValueError('pinned model hash mismatch: ' + name)
    if set(MODEL_FILE_GIT_SHA1) != {'grapheme_mtl_merged_expanded_v1.json', 'Cangjie5_TC.json'}:
        raise ValueError('Multilingual Git pin inventory is incomplete')
    for name, expected in MODEL_FILE_GIT_SHA1.items():
        if git_blob_sha1(root / 'model' / name) != expected:
            raise ValueError('pinned model Git object mismatch: ' + name)

    cache_cangjie = root / 'model' / Path(HF_CACHE_CANGJIE)
    if file_sha256(cache_cangjie) != MODEL_FILE_SHA256['Cangjie5_TC.json']:
        raise ValueError('Hugging Face offline cache Cangjie hash mismatch')
    cache_ref = root / 'model' / Path(HF_CACHE_MAIN_REF)
    if cache_ref.read_text(encoding='utf-8') != MODEL_REVISION:
        raise ValueError('Hugging Face offline cache reference mismatch')

    archive = root / 'model/pkuseg/spacy_ontonotes.zip'
    if file_sha256(archive) != PKUSEG_ARCHIVE_SHA256:
        raise ValueError('pinned pkuseg hash mismatch: spacy_ontonotes.zip')
    if set(PKUSEG_FILE_SHA256) != {'features.msgpack', 'weights.npz'}:
        raise ValueError('pkuseg model pin inventory is incomplete')
    for name, expected in PKUSEG_FILE_SHA256.items():
        if file_sha256(root / 'model/pkuseg/spacy_ontonotes' / name) != expected:
            raise ValueError('pinned pkuseg hash mismatch: ' + name)

    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob('*')
        if path.is_file() and path != root / 'manifest.json'
    }
    if normalized != actual:
        raise ValueError('Multilingual payload inventory differs from manifest')

    return MultilingualInstallation(
        root,
        root / 'worker/MultilingualWorker.exe',
        root / 'model',
        hashlib.sha256(raw_manifest).hexdigest(),
    )
