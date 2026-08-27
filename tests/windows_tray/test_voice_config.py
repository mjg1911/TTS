from pathlib import Path

import pytest

from piper.windows_tray.voice_config import resolve_voice_reference


def test_voice_identifier_resolves_from_tray_voice_directory(tmp_path: Path) -> None:
    model = tmp_path / "en_GB-alba-medium.onnx"
    config = tmp_path / "en_GB-alba-medium.onnx.json"
    model.write_bytes(b"model")
    config.write_text("{}", encoding="utf-8")

    assert resolve_voice_reference("en_GB-alba-medium", [tmp_path]) == model


def test_missing_voice_reference_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        resolve_voice_reference("en_GB-alba-medium", [tmp_path])
