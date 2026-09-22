from __future__ import annotations

from pathlib import Path
from queue import Empty, Queue
import sys
from threading import Thread
from typing import Optional

from piper.kokoro_assets import verify_kokoro_installation
from piper.windows_tray.kokoro_protocol import (
    PROTOCOL_VERSION,
    ProtocolError,
    encode_audio,
    read_frame,
    validate_initialize,
    validate_synthesize,
    write_frame,
)

from .runtime import KokoroRuntime

WORKER_VERSION = "1"
KOKORO_VERSION = "0.9.4"


def _read_messages(stdin, inbox: Queue) -> None:
    while True:
        try:
            inbox.put(read_frame(stdin))
        except EOFError:
            inbox.put(None)
            return
        except BaseException as error:
            inbox.put(error)
            return


def _receive(inbox: Queue):
    item = inbox.get()
    if item is None:
        raise EOFError("parent pipe closed")
    if isinstance(item, BaseException):
        raise item
    return item


def _cancel_requested(inbox: Queue, request_id: int) -> bool:
    cancelled = False
    while True:
        try:
            item = inbox.get_nowait()
        except Empty:
            return cancelled
        if item is None:
            return cancelled
        if isinstance(item, BaseException):
            raise item
        if item.get("type") == "cancel" and item.get("request_id") == request_id:
            cancelled = True
            continue
        inbox.put(item)
        return cancelled


def _frozen_install_root() -> Path:
    if not getattr(sys, "frozen", False):
        raise RuntimeError("install_root is required for an unfrozen Kokoro worker")
    return Path(sys.executable).resolve().parent.parent


def main(stdin=None, stdout=None, stderr=None, install_root: Optional[Path] = None) -> int:
    if stdin is None:
        if sys.stdin is None or not hasattr(sys.stdin, "buffer"):
            raise RuntimeError("Kokoro worker stdin is unavailable")
        stdin = sys.stdin.buffer
    if stdout is None:
        if sys.stdout is None or not hasattr(sys.stdout, "buffer"):
            raise RuntimeError("Kokoro worker stdout is unavailable")
        stdout = sys.stdout.buffer
    stderr = stderr or sys.stderr
    root = Path(install_root) if install_root is not None else _frozen_install_root()

    inbox = Queue()
    reader = Thread(
        target=_read_messages,
        args=(stdin, inbox),
        name="kokoro-protocol-reader",
        daemon=True,
    )
    reader.start()
    write_frame(
        stdout,
        {
            "type": "hello",
            "protocol_version": PROTOCOL_VERSION,
            "worker_version": WORKER_VERSION,
            "kokoro_version": KOKORO_VERSION,
        },
    )

    runtime: Optional[KokoroRuntime] = None
    while True:
        try:
            message = _receive(inbox)
        except EOFError:
            return 0
        message_type = message.get("type")
        if message_type == "shutdown":
            return 0
        if message_type == "initialize":
            validate_initialize(message)
            installation = verify_kokoro_installation(root)
            if installation.manifest_sha256 != message["manifest_sha256"]:
                raise ProtocolError("manifest fingerprint mismatch")
            runtime = KokoroRuntime(
                installation.config_path,
                installation.model_path,
                installation.voices,
            )
            runtime.load()
            write_frame(stdout, {"type": "ready"})
            continue
        if message_type != "synthesize" or runtime is None:
            raise ProtocolError("worker received message before initialization")

        validate_synthesize(message)
        request_id = int(message["request_id"])
        cancelled = False
        try:
            for pcm in runtime.synthesize_segments(
                str(message["text"]), str(message["voice_id"])
            ):
                if _cancel_requested(inbox, request_id):
                    cancelled = True
                    break
                write_frame(
                    stdout,
                    {"type": "audio", "request_id": request_id, "audio": encode_audio(pcm)},
                )
            if cancelled or _cancel_requested(inbox, request_id):
                write_frame(stdout, {"type": "response_cancelled", "request_id": request_id})
            else:
                write_frame(stdout, {"type": "response_end", "request_id": request_id})
        except Exception as error:
            print(
                "kokoro request failed request_id=%d category=%s"
                % (request_id, type(error).__name__),
                file=stderr,
            )
            write_frame(
                stdout,
                {"type": "response_error", "request_id": request_id, "category": "inference"},
            )


if __name__ == "__main__":
    raise SystemExit(main())
