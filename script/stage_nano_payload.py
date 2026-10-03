"""Explicit online staging; runtime never calls these download APIs."""
import argparse
import json
import shutil
import tempfile
from pathlib import Path
from piper.nano_assets import SOURCE_REVISION, MODEL_REVISION, REQUIRED_MODEL_FILES, MODEL_FILE_SHA256, file_sha256, inspect_nano_installation


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker-dir', type=Path, required=True)
    parser.add_argument('--model-dir', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('staging output already exists; choose a fresh directory')
    model = args.model_dir
    if model is None:
        from huggingface_hub import snapshot_download
        model = Path(snapshot_download('ResembleAI/chatterbox-nano', revision=MODEL_REVISION, allow_patterns=list(REQUIRED_MODEL_FILES)))
    for name in REQUIRED_MODEL_FILES:
        if not (model / name).is_file():
            raise FileNotFoundError(model / name)
        if file_sha256(model / name) != MODEL_FILE_SHA256[name]:
            raise ValueError('pinned model hash mismatch: ' + name)
    if not (args.worker_dir / 'NanoWorker.exe').is_file():
        raise FileNotFoundError(args.worker_dir / 'NanoWorker.exe')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.' + args.output.name + '.staging-', dir=args.output.parent))
    try:
        shutil.copytree(args.worker_dir, staging / 'worker')
        (staging / 'model').mkdir()
        for name in REQUIRED_MODEL_FILES:
            shutil.copy2(model / name, staging / 'model' / name)
        files = {path.relative_to(staging).as_posix(): file_sha256(path) for path in staging.rglob('*') if path.is_file()}
        manifest = dict(manifest_version=1, engine='Chatterbox Nano', source_revision=SOURCE_REVISION, model_revision=MODEL_REVISION, files=files)
        (staging / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf8')
        inspect_nano_installation(staging)
        if args.output.exists():
            raise ValueError('staging output appeared while staging; choose a fresh directory')
        staging.rename(args.output)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

if __name__ == '__main__':
    main()
