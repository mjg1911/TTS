from collections.abc import Iterable
from pathlib import Path
from typing import Tuple

from piper import PiperVoice


def resolve_voice_reference(reference: str, data_dirs: Iterable[Path]) -> Path:
    direct = Path(reference).expanduser()
    candidates = [direct]
    if direct.suffix.lower() != ".onnx":
        candidates.extend(
            Path(directory) / (reference + ".onnx") for directory in data_dirs
        )

    for candidate in candidates:
        if candidate.is_file() and candidate.with_suffix(candidate.suffix + ".json").is_file():
            return candidate.resolve()
    raise FileNotFoundError(reference)


def load_voice_candidate(
    reference: str, data_dirs: Iterable[Path]
) -> Tuple[Path, PiperVoice]:
    model_path = resolve_voice_reference(reference, data_dirs)
    return model_path, PiperVoice.load(model_path)
