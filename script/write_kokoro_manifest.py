from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main(root_text: str) -> int:
    root = Path(root_text).resolve()
    files = {
        path.relative_to(root).as_posix(): sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    }
    manifest = {
        "manifest_version": 1,
        "worker_version": "1",
        "kokoro_version": "0.9.4",
        "model_revision": "c3327e9bac3dbe55779397bfa82de0f8806fb3bc",
        "worker": {"executable": "worker/KokoroWorker.exe"},
        "model": {
            "config": "model/config.json",
            "weights": "model/kokoro-v1_0.pth",
        },
        "voices": {
            "af_heart": {"path": "voices/af_heart.pt", "language": "a"}
        },
        "required_groups": {
            "spacy": "worker/_internal/en_core_web_sm",
            "misaki_data": "worker/_internal/misaki/data",
            "espeak_ng": "worker/_internal/espeakng_loader",
        },
        "files": files,
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: write_kokoro_manifest.py PAYLOAD_ROOT")
    raise SystemExit(main(sys.argv[1]))
