"""Tests for discovering reusable Chatterbox reference recordings."""

import importlib
from pathlib import Path

import pytest


@pytest.fixture
def voice_module():
    return importlib.import_module("piper.windows_tray.chatterbox_voice")


def _write(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not decoded during discovery")
    return path


def test_lists_only_wav_files_with_absolute_paths_without_decoding(
    tmp_path, voice_module
):
    directory = tmp_path / "References"
    lower = _write(directory / "lower.wav")
    upper = _write(directory / "upper.WAV")
    _write(directory / "notes.txt")
    _write(directory / "audio.wav.bak")
    _write(directory / "folder.wav" / "nested.txt")

    voices = voice_module.list_reference_voices(directory=directory)

    assert voices == {
        "lower": str(lower.resolve()),
        "upper": str(upper.resolve()),
    }


def test_absent_managed_folder_returns_empty_mapping(tmp_path, voice_module):
    assert voice_module.list_reference_voices(directory=tmp_path / "not-created") == {}


def test_removes_only_a_trailing_hyphen_and_32_hex_uuid(tmp_path, voice_module):
    directory = tmp_path / "References"
    managed = _write(directory / "Grandma-takes-1-0123456789abcdef0123456789abcdef.wav")
    ordinary = _write(
        directory / "Grandma-takes-1-0123456789abcdef0123456789abcdeg.wav"
    )

    voices = voice_module.list_reference_voices(directory=directory)

    assert voices == {
        "Grandma-takes-1": str(managed.resolve()),
        "Grandma-takes-1-0123456789abcdef0123456789abcdeg": str(ordinary.resolve()),
    }


def test_duplicate_stems_and_literal_numbered_stems_get_unique_labels(
    tmp_path, voice_module
):
    directory = tmp_path / "References"
    first = _write(directory / "Ada.wav")
    literal = _write(directory / "Ada (2).wav")
    second = _write(directory / "Ada-0123456789abcdef0123456789abcdef.wav")

    voices = voice_module.list_reference_voices(directory=directory)

    assert voices == {
        "Ada": str(second.resolve()),
        "Ada (2)": str(literal.resolve()),
        "Ada (3)": str(first.resolve()),
    }
    assert len(voices) == len(set(voices))
    assert set(voices.values()) == {
        str(first.resolve()),
        str(literal.resolve()),
        str(second.resolve()),
    }


@pytest.mark.parametrize(
    "current_name, expected_label",
    [
        ("outside/External voice.wav", "External voice (unavailable)"),
        ("missing/Studio-0123456789abcdef0123456789abcdef.wav", "Studio (unavailable)"),
    ],
)
def test_preserves_external_or_missing_current_selection(
    tmp_path, voice_module, current_name, expected_label
):
    current = tmp_path / current_name
    voices = voice_module.list_reference_voices(
        current=str(current), directory=tmp_path / "References"
    )

    assert voices == {expected_label: str(current.resolve())}


def test_existing_external_recording_is_not_marked_unavailable(tmp_path, voice_module):
    current = _write(tmp_path / "outside" / "External voice.wav")

    voices = voice_module.list_reference_voices(
        current=str(current), directory=tmp_path / "References"
    )

    assert voices == {"External voice": str(current.resolve())}


def test_uuid_only_stem_uses_a_readable_fallback_label(tmp_path, voice_module):
    recording = _write(
        tmp_path / "References" / "-0123456789abcdef0123456789abcdef.wav"
    )

    voices = voice_module.list_reference_voices(directory=recording.parent)

    assert voices == {"Reference voice": str(recording.resolve())}


def test_current_discovered_path_is_not_added_again_as_unavailable(
    tmp_path, voice_module
):
    recording = _write(tmp_path / "References" / "Guide.wav")

    voices = voice_module.list_reference_voices(
        current=str(recording), directory=recording.parent
    )

    assert voices == {"Guide": str(recording.resolve())}


def test_inaccessible_reference_folder_raises_reference_clip_error(
    tmp_path, monkeypatch, voice_module
):
    directory = tmp_path / "References"
    directory.mkdir()
    original_iterdir = Path.iterdir

    def denied(path):
        if path == directory.resolve():
            raise PermissionError("access denied")
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", denied)

    with pytest.raises(voice_module.ReferenceClipError, match="folder"):
        voice_module.list_reference_voices(directory=directory)
