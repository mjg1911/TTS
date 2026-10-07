"""Stage one verified Chatterbox worker with one or both pinned model sets."""
import argparse
import json
import shutil
import tempfile
from pathlib import Path

from piper import nano_assets, turbo_assets
from piper.chatterbox_assets import file_sha256, inspect_chatterbox_installation


ENGINE_ASSETS = {"nano": nano_assets, "turbo": turbo_assets}


def _download_model(engine):
    from huggingface_hub import snapshot_download

    assets = ENGINE_ASSETS[engine]
    return Path(
        snapshot_download(
            repo_id=assets.MODEL_REPO,
            revision=assets.MODEL_REVISION,
            allow_patterns=list(assets.REQUIRED_MODEL_FILES),
        )
    )


def _validated_model_dir(engine, model_dir):
    assets = ENGINE_ASSETS[engine]
    if set(assets.MODEL_FILE_SHA256) != set(assets.REQUIRED_MODEL_FILES):
        raise ValueError("incomplete pinned model inventory: " + engine)
    model_dir = Path(model_dir).resolve()
    for name in assets.REQUIRED_MODEL_FILES:
        model_file = model_dir / name
        if not model_file.is_file():
            raise FileNotFoundError(model_file)
        if file_sha256(model_file) != assets.MODEL_FILE_SHA256[name]:
            raise ValueError("pinned model hash mismatch: " + engine + "/" + name)
    return model_dir


def stage_payload(
    worker_dir,
    output,
    *,
    nano_model_dir=None,
    turbo_model_dir=None,
    download_models=(),
):
    worker_dir = Path(worker_dir).resolve()
    output = Path(output).resolve()
    worker_executable = worker_dir / "ChatterboxWorker.exe"
    if not worker_executable.is_file():
        raise FileNotFoundError(worker_executable)
    if nano_assets.SOURCE_REVISION != turbo_assets.SOURCE_REVISION:
        raise ValueError("Nano and Turbo Chatterbox source revisions differ")
    if output.exists():
        raise ValueError("staging output already exists; choose a fresh directory")

    supplied = {"nano": nano_model_dir, "turbo": turbo_model_dir}
    download_models = set(download_models)
    if not download_models <= set(ENGINE_ASSETS):
        raise ValueError("unsupported Chatterbox model download selection")
    if any(supplied[engine] is not None for engine in download_models):
        raise ValueError("choose a model directory or download switch for each engine")
    model_dirs = {
        engine: _validated_model_dir(engine, model_dir)
        for engine, model_dir in supplied.items()
        if model_dir is not None
    }
    for engine in download_models:
        model_dirs[engine] = _validated_model_dir(engine, _download_model(engine))
    if not model_dirs:
        raise ValueError("at least one pinned Chatterbox model directory is required")

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix="." + output.name + ".staging-",
            dir=output.parent,
        )
    )
    try:
        shutil.copytree(worker_dir, staging / "worker")
        model_metadata = {}
        for engine, model_dir in model_dirs.items():
            assets = ENGINE_ASSETS[engine]
            staged_model = staging / "models" / engine
            staged_model.mkdir(parents=True)
            for name in assets.REQUIRED_MODEL_FILES:
                shutil.copy2(model_dir / name, staged_model / name)
            model_metadata[engine] = {
                "model_revision": assets.MODEL_REVISION,
                "model_repo": assets.MODEL_REPO,
            }

        files = {
            path.relative_to(staging).as_posix(): file_sha256(path)
            for path in staging.rglob("*")
            if path.is_file()
        }
        manifest = {
            "manifest_version": 2,
            "runtime": "Chatterbox",
            "source_revision": nano_assets.SOURCE_REVISION,
            "models": model_metadata,
            "files": files,
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        inspect_chatterbox_installation(staging, next(iter(model_dirs)))
        if output.exists():
            raise ValueError("staging output appeared while staging; choose a fresh directory")
        staging.rename(output)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--nano-model-dir", type=Path)
    parser.add_argument("--turbo-model-dir", type=Path)
    parser.add_argument("--download-nano", action="store_true")
    parser.add_argument("--download-turbo", action="store_true")
    args = parser.parse_args()
    stage_payload(
        args.worker_dir,
        args.output,
        nano_model_dir=args.nano_model_dir,
        turbo_model_dir=args.turbo_model_dir,
        download_models={
            engine
            for engine in ("nano", "turbo")
            if getattr(args, "download_" + engine)
        },
    )


if __name__ == "__main__":
    main()
