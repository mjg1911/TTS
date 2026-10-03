"""Storage and validation for Chatterbox reference recordings."""

from __future__ import annotations

import os
import re
import shutil
import wave
from pathlib import Path
from typing import Optional
from uuid import uuid4


MIN_REFERENCE_SECONDS = 5
MAX_REFERENCE_CLIP_BYTES = 100 * 1024 * 1024
MIN_SAMPLE_RATE = 8_000
MAX_SAMPLE_RATE = 192_000
_SUPPORTED_SAMPLE_WIDTHS = {1, 2, 3, 4}


class ReferenceClipError(ValueError):
    """Raised when a reference recording cannot be used safely."""


def _default_reference_directory() -> Path:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / "Piper" / "Chatterbox" / "References"

    if os.name == "nt":
        return (
            Path.home()
            / "AppData"
            / "Local"
            / "Piper"
            / "Chatterbox"
            / "References"
        )

    data_home = os.environ.get("XDG_DATA_HOME")
    root = Path(data_home) if data_home else Path.home() / ".local" / "share"
    return root / "Piper" / "Chatterbox" / "References"


def validate_reference_clip(source: Path) -> Path:
    """Validate a PCM WAV reference and return its absolute path.

    The recording must be longer than Chatterbox's five-second minimum, fit
    within the import size limit, and contain complete, non-silent audio data.
    This function does not copy or modify the file.
    """

    try:
        path = Path(source).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise ReferenceClipError("Select an existing reference WAV file.") from error

    try:
        if not path.is_file():
            raise ReferenceClipError("The reference clip must be a WAV file.")
        if path.suffix.lower() != ".wav":
            raise ReferenceClipError("The reference clip must use the .wav format.")
        file_size = path.stat().st_size
    except OSError as error:
        raise ReferenceClipError("The reference clip could not be read.") from error

    if file_size > MAX_REFERENCE_CLIP_BYTES:
        raise ReferenceClipError(
            "The reference clip is too large (maximum 100 MiB)."
        )
    if file_size == 0:
        raise ReferenceClipError("The reference WAV file is empty.")

    try:
        with wave.open(str(path), "rb") as wav:
            if wav.getcomptype() != "NONE":
                raise ReferenceClipError(
                    "The reference clip must be an uncompressed PCM WAV file."
                )
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            declared_frames = wav.getnframes()

            if channels not in (1, 2):
                raise ReferenceClipError(
                    "The reference WAV must have one or two audio channels."
                )
            if sample_width not in _SUPPORTED_SAMPLE_WIDTHS:
                raise ReferenceClipError(
                    "The reference WAV must use 8, 16, 24, or 32-bit PCM audio."
                )
            if not MIN_SAMPLE_RATE <= sample_rate <= MAX_SAMPLE_RATE:
                raise ReferenceClipError(
                    "The reference WAV sample rate must be between 8 and 192 kHz."
                )
            if declared_frames <= 0:
                raise ReferenceClipError("The reference WAV contains no audio data.")

            frame_width = channels * sample_width
            frames_read = 0
            has_audio = False
            silence_byte = b"\x80" if sample_width == 1 else b"\x00"
            while frames_read < declared_frames:
                requested = min(65_536, declared_frames - frames_read)
                data = wav.readframes(requested)
                if not data:
                    break
                if len(data) % frame_width:
                    raise ReferenceClipError(
                        "The reference WAV contains an incomplete audio frame."
                    )
                frames_read += len(data) // frame_width
                if data != silence_byte * len(data):
                    has_audio = True

            if frames_read != declared_frames:
                raise ReferenceClipError(
                    "The reference WAV is truncated or has incomplete audio data."
                )
    except ReferenceClipError:
        raise
    except (EOFError, OSError, ValueError, wave.Error) as error:
        raise ReferenceClipError(
            "The reference clip is not a readable PCM WAV file."
        ) from error

    if frames_read / sample_rate <= MIN_REFERENCE_SECONDS:
        raise ReferenceClipError(
            "The reference clip must be longer than 5 seconds."
        )
    if not has_audio:
        raise ReferenceClipError("The reference WAV contains only silence.")

    return path


def import_reference_clip(
    source: Path, directory: Optional[Path] = None
) -> Path:
    """Copy a validated WAV to Piper's managed Chatterbox data directory."""

    source_path = validate_reference_clip(source)
    target_directory = Path(directory) if directory is not None else _default_reference_directory()
    try:
        target_directory = target_directory.expanduser().resolve()
        target_directory.mkdir(parents=True, exist_ok=True)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise ReferenceClipError("Piper could not create its reference clip folder.") from error

    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", source_path.stem).strip(" .")
    stem = (stem or "reference")[:80]
    for _ in range(10):
        destination = target_directory / (stem + "-" + uuid4().hex + ".wav")
        try:
            with source_path.open("rb") as source_file, destination.open("xb") as target_file:
                shutil.copyfileobj(source_file, target_file, length=1024 * 1024)
        except FileExistsError:
            continue
        except OSError as error:
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass
            raise ReferenceClipError("Piper could not save the reference clip.") from error

        try:
            validate_reference_clip(destination)
        except ReferenceClipError:
            destination.unlink(missing_ok=True)
            raise
        return destination.resolve()

    raise ReferenceClipError("Piper could not create a unique reference clip file.")
