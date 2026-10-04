"""Stage the separately pinned Multilingual worker and offline model payload."""
import argparse
import json
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from piper.multilingual_assets import (
    ENGINE,
    HF_CACHE_CANGJIE,
    HF_CACHE_MAIN_REF,
    MODEL_FILE_SHA256,
    MODEL_REPO,
    MODEL_REVISION,
    PKUSEG_ARCHIVE_SHA256,
    PKUSEG_FILE_SHA256,
    PKUSEG_MODEL_URL,
    REQUIRED_MODEL_FILES,
    SOURCE_REVISION,
    file_sha256,
    inspect_multilingual_installation,
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


def _download_pkuseg_archive(target):
    with urllib.request.urlopen(PKUSEG_MODEL_URL, timeout=60) as response, Path(target).open('wb') as output:
        shutil.copyfileobj(response, output)


def _stage_pkuseg_archive(archive, model_dir):
    archive = Path(archive)
    if not archive.is_file() or file_sha256(archive) != PKUSEG_ARCHIVE_SHA256:
        raise ValueError('pinned pkuseg archive hash mismatch')

    extracted_dir = model_dir / 'pkuseg/spacy_ontonotes'
    extracted_dir.mkdir(parents=True)
    with zipfile.ZipFile(archive) as zipped:
        members = zipped.infolist()
        names = {member.filename for member in members}
        if names != set(PKUSEG_FILE_SHA256) or len(members) != len(names):
            raise ValueError('pkuseg archive inventory mismatch')
        for member in members:
            relative = PurePosixPath(member.filename)
            mode = (member.external_attr >> 16) & 0o170000
            if (relative.is_absolute() or '..' in relative.parts or '\\' in member.filename
                    or member.is_dir() or mode == 0o120000):
                raise ValueError('unsafe pkuseg archive member path')
            destination = extracted_dir.joinpath(*relative.parts)
            with zipped.open(member) as source, destination.open('wb') as output:
                shutil.copyfileobj(source, output)
            if file_sha256(destination) != PKUSEG_FILE_SHA256[member.filename]:
                raise ValueError('pinned pkuseg file hash mismatch: ' + member.filename)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker-dir', type=Path, required=True)
    parser.add_argument('--model-dir', type=Path)
    parser.add_argument('--pkuseg-archive', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()

    output = args.output.resolve()
    if output.exists():
        raise ValueError('staging output already exists; choose a fresh directory')
    worker_dir = args.worker_dir.resolve()
    worker_executable = worker_dir / 'MultilingualWorker.exe'
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
    downloaded_archive_dir = None
    try:
        shutil.copytree(worker_dir, staging / 'worker')
        staged_model = staging / 'model'
        staged_model.mkdir()
        for name in REQUIRED_MODEL_FILES:
            shutil.copy2(model_dir / name, staged_model / name)

        cache_snapshot = staged_model / HF_CACHE_CANGJIE
        cache_snapshot.parent.mkdir(parents=True)
        shutil.copy2(staged_model / 'Cangjie5_TC.json', cache_snapshot)
        cache_ref = staged_model / HF_CACHE_MAIN_REF
        cache_ref.parent.mkdir(parents=True)
        cache_ref.write_text(MODEL_REVISION, encoding='utf-8')

        pkuseg_dir = staged_model / 'pkuseg'
        pkuseg_dir.mkdir()
        archive = args.pkuseg_archive
        if archive is None:
            downloaded_archive_dir = Path(tempfile.mkdtemp(prefix='.pkuseg-download-', dir=output.parent))
            archive = downloaded_archive_dir / 'spacy_ontonotes.zip'
            _download_pkuseg_archive(archive)
        staged_archive = pkuseg_dir / 'spacy_ontonotes.zip'
        shutil.copy2(archive, staged_archive)
        if file_sha256(staged_archive) != PKUSEG_ARCHIVE_SHA256:
            raise ValueError('pinned pkuseg archive hash mismatch')
        _stage_pkuseg_archive(staged_archive, staged_model)

        files = {
            path.relative_to(staging).as_posix(): file_sha256(path)
            for path in staging.rglob('*')
            if path.is_file()
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
        inspect_multilingual_installation(staging)
        if output.exists():
            raise ValueError('staging output appeared while staging; choose a fresh directory')
        staging.rename(output)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        if downloaded_archive_dir is not None:
            shutil.rmtree(downloaded_archive_dir, ignore_errors=True)


if __name__ == '__main__':
    main()
