"""Create verified GitHub release parts from a staged shared Chatterbox payload."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import tempfile
import zipfile

from piper.chatterbox_assets import inspect_chatterbox_installation
from piper.windows_tray.model_download import MAX_PART_BYTES

RELEASE = "v1.10.0"
DOWNLOAD_BASE = "https://github.com/mjg1911/TTS/releases/download"
BLOCK_BYTES = 1024 * 1024


def prepare_model_release(payload_dir, output, catalog_path, release=RELEASE,
                          *, max_part_bytes=MAX_PART_BYTES):
    payload = Path(payload_dir).resolve()
    output = Path(output).resolve()
    catalog_path = Path(catalog_path).resolve()
    if release != RELEASE:
        raise ValueError(f"This application requires release {RELEASE}")
    if not 0 < max_part_bytes <= MAX_PART_BYTES:
        raise ValueError("Invalid release part size")
    if output == payload or payload in output.parents:
        raise ValueError("Release output must be outside the payload")
    for engine in ("nano", "turbo"):
        inspect_chatterbox_installation(payload, engine)
    manifest = json.loads((payload / "manifest.json").read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=True)
    catalog = {"version": 1, "release": release, "components": {}}
    for component in ("worker", "nano", "turbo"):
        prefix = "worker/" if component == "worker" else f"models/{component}/"
        files = sorted(name for name in manifest["files"] if name.startswith(prefix))
        if not files:
            raise ValueError(f"No verified files for {component}")
        with tempfile.TemporaryDirectory(prefix="model-release-", dir=output) as scratch:
            archive_path = Path(scratch) / "payload.zip"
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED,
                                 compresslevel=6, allowZip64=True) as archive:
                for name in files:
                    info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o100644 << 16
                    info.file_size = (payload / name).stat().st_size
                    with (payload / name).open("rb") as source, archive.open(
                        info, "w", force_zip64=True
                    ) as target:
                        while block := source.read(BLOCK_BYTES):
                            target.write(block)
            parts = []
            with archive_path.open("rb") as source:
                number = 1
                while source.tell() < archive_path.stat().st_size:
                    filename = f"chatterbox-{component}-{release}.zip.part{number:03d}"
                    asset = output / filename
                    digest = hashlib.sha256()
                    size = 0
                    with asset.open("wb") as target:
                        while size < max_part_bytes:
                            block = source.read(min(BLOCK_BYTES, max_part_bytes - size))
                            if not block:
                                break
                            target.write(block)
                            digest.update(block)
                            size += len(block)
                    parts.append({"url": f"{DOWNLOAD_BASE}/{release}/{filename}",
                                  "size": size, "sha256": digest.hexdigest()})
                    number += 1
            catalog["components"][component] = {"parts": parts}
            current_names = {Path(part["url"]).name for part in parts}
            generated_pattern = re.compile(
                re.escape(f"chatterbox-{component}-{release}.zip.part") + r"[0-9]{3,}"
            )
            for previous in output.iterdir():
                if (previous.is_file() and generated_pattern.fullmatch(previous.name)
                        and previous.name not in current_names):
                    previous.unlink()
            print(f"Prepared {component}: {len(parts)} part(s), "
                  f"{sum(part['size'] for part in parts):,} bytes", flush=True)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps(catalog, indent=2) + "\n", encoding="utf-8")
    return catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--release", default=RELEASE)
    args = parser.parse_args()
    prepare_model_release(args.payload_dir, args.output, args.catalog, args.release)


if __name__ == "__main__":
    main()
