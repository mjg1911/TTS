"""Framed Nano helper; stdout belongs exclusively to the protocol."""
import argparse
import contextlib
import getpass
import os
import sys
import tempfile
from pathlib import Path
from piper.nano_assets import inspect_nano_installation
from piper.windows_tray.kokoro_protocol import read_frame, write_frame, encode_audio, validate_initialize, validate_synthesize
from .runtime import load_model, generate_chunks


def _configure_numba_cache(installation_root):
    root = Path(installation_root).resolve()
    candidates = []
    if os.environ.get('LOCALAPPDATA'):
        candidates.append(Path(os.environ['LOCALAPPDATA']) / 'Piper' / 'Numba')
    if os.environ.get('XDG_CACHE_HOME'):
        candidates.append(Path(os.environ['XDG_CACHE_HOME']) / 'Piper' / 'Numba')
    try:
        candidates.append(Path.home() / '.cache' / 'Piper' / 'Numba')
    except (OSError, RuntimeError):
        pass
    candidates.append(Path(tempfile.gettempdir()) / ('piper-' + getpass.getuser()) / 'Numba')
    seen = set()
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate == root or root in candidate.parents:
            continue
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(prefix='.numba-cache-check-', dir=candidate):
                pass
        except OSError:
            continue
        os.environ['NUMBA_CACHE_DIR'] = str(candidate)
        return candidate
    raise OSError('could not create a writable per-user Numba cache outside the Nano installation')


def serve(root, incoming, outgoing):
    write_frame(outgoing, {'type': 'hello', 'engine': 'Chatterbox Nano', 'protocol_version': 1})
    request = read_frame(incoming)
    validate_initialize(request)
    installation = inspect_nano_installation(root)
    if request['manifest_sha256'] != installation.manifest_sha256:
        raise ValueError('Nano manifest identity changed')
    _configure_numba_cache(installation.root)
    with contextlib.redirect_stdout(sys.stderr):
        model = load_model(installation.model_dir)
    write_frame(outgoing, {'type': 'ready', 'sample_rate': model.sr})
    while True:
        try:
            request = read_frame(incoming)
        except EOFError:
            return
        if request.get('type') == 'shutdown':
            return
        validate_synthesize(request)
        if request.get('voice_id') != 'default':
            raise ValueError('Nano supports only its default voice')
        request_id = request['request_id']
        try:
            with contextlib.redirect_stdout(sys.stderr):
                for audio in generate_chunks(model, request['text']):
                    write_frame(outgoing, {'type': 'audio', 'request_id': request_id, 'audio': encode_audio(audio)})
            write_frame(outgoing, {'type': 'response_end', 'request_id': request_id})
        except Exception as error:
            print(str(error), file=sys.stderr)
            write_frame(outgoing, {'type': 'response_error', 'request_id': request_id, 'category': 'synthesis_failed'})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    incoming, outgoing = sys.stdin.buffer, sys.stdout.buffer
    try:
        serve(args.root, incoming, outgoing)
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
