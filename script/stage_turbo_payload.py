"""Stage the separately pinned Turbo worker and offline model payload."""
import argparse
import json
import shutil
import tempfile
from pathlib import Path

from piper.turbo_assets import (
    ENGINE,
    MODEL_FILE_SHA256,
    MODEL_REPO,
    MODEL_REVISION,
    REQUIRED_MODEL_FILES,
    SOURCE_REVISION,
    file_sha256,
    inspect_turbo_installation,
)


def _validate_model_dir(model_dir):
    model_dir = Path(model_dir)
    for name in REQUIRED_MODEL_FILES:
        path = model_dir / name
        if not path.is_file():
            raise FileNotFoundError(path)
        if file_sha256(path) != MODEL_FILE_SHA256[name]:
            raise ValueError('pinned model hash mismatch: ' + name)
    return model_dir


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker-dir', type=Path, required=True)
    parser.add_argument('--model-dir', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()

    output = args.output.resolve()
    if output.exists():
        raise ValueError('staging output already exists; choose a fresh directory')
    worker_dir = args.worker_dir.resolve()
    worker_executable = worker_dir / 'TurboWorker.exe'
    if not worker_executable.is_file():
        raise FileNotFoundError(worker_executable)

    model_dir = args.model_dir
    if model_dir is None:
        from huggingface_hub import snapshot_download
        model_dir = Path(snapshot_download(
            repo_id=MODEL_REPO,
            revision=MODEL_REVISION,
            allow_patterns=list(REQUIRED_MODEL_FILES),
        ))
    model_dir = _validate_model_dir(model_dir)

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.' + output.name + '.staging-', dir=output.parent))
    try:
        shutil.copytree(worker_dir, staging / 'worker')
        staged_model = staging / 'model'
        staged_model.mkdir()
        for name in REQUIRED_MODEL_FILES:
            shutil.copy2(model_dir / name, staged_model / name)

        files = {
            path.relative_to(staging).as_posix(): file_sha256(path)
            for path in staging.rglob('*') if path.is_file()
        }
        manifest = {
            'manifest_version': 1,
            'engine': ENGINE,
            'source_revision': SOURCE_REVISION,
            'model_repo': MODEL_REPO,
            'model_revision': MODEL_REVISION,
            'files': files,
        }
        (staging / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        inspect_turbo_installation(staging)
        if output.exists():
            raise ValueError('staging output appeared while staging; choose a fresh directory')
        staging.rename(output)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


if __name__ == '__main__':
    main()
