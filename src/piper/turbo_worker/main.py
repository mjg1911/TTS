"""Framed GPU worker. Only protocol frames may be written to stdout."""
import argparse
import contextlib
import sys
from pathlib import Path

from piper.turbo_assets import ENGINE, inspect_turbo_installation
from piper.turbo_options import validate_delivery_mode
from piper.nano_worker.main import _configure_numba_cache
from piper.windows_tray.worker_protocol import (
    encode_audio,
    read_frame,
    validate_initialize,
    validate_synthesize,
    write_frame,
)
from .runtime import generate_chunks, load_model


def serve(root, incoming, outgoing):
    write_frame(outgoing, {'type': 'hello', 'engine': ENGINE, 'protocol_version': 1})
    try:
        request = read_frame(incoming)
        required = {'type', 'manifest_sha256', 'device'}
        if not required <= set(request) or not set(request) <= required | {'reference_clip'}:
            raise ValueError('Invalid Turbo initialization fields')
        validate_initialize({key: request[key] for key in ('type', 'manifest_sha256')})
        if request['device'] != 'cuda':
            raise ValueError('Chatterbox Turbo requires CUDA; CPU fallback is disabled.')
        reference_clip = request.get('reference_clip')
        if 'reference_clip' in request and (not isinstance(reference_clip, str) or not reference_clip):
            raise ValueError('Reference clip must be an absolute WAV path')
        installation = inspect_turbo_installation(root)
        if request['manifest_sha256'] != installation.manifest_sha256:
            raise ValueError('Turbo manifest identity changed')
        _configure_numba_cache(installation.root)
        with contextlib.redirect_stdout(sys.stderr):
            model = load_model(installation.model_dir, reference_clip=reference_clip)
    except Exception as error:
        print(str(error), file=sys.stderr)
        write_frame(outgoing, {'type': 'startup_error', 'message': str(error)[:1000]})
        return
    write_frame(outgoing, {
        'type': 'ready',
        'sample_rate': model.sr,
        'device': 'cuda',
        'device_message': 'Chatterbox Turbo (350M) uses GPU (CUDA).',
    })
    while True:
        try:
            request = read_frame(incoming)
        except EOFError:
            return
        if request.get('type') == 'shutdown':
            return
        validate_synthesize(request)
        delivery_mode = validate_delivery_mode(request.get('delivery_mode', ''))
        if request['voice_id'] != 'default':
            raise ValueError('Unknown Turbo voice')
        request_id = request['request_id']
        try:
            with contextlib.redirect_stdout(sys.stderr):
                for audio in generate_chunks(
                    model, request['text'], delivery_mode=delivery_mode
                ):
                    write_frame(outgoing, {
                        'type': 'audio', 'request_id': request_id, 'audio': encode_audio(audio),
                    })
            write_frame(outgoing, {'type': 'response_end', 'request_id': request_id})
        except Exception as error:
            print(str(error), file=sys.stderr)
            write_frame(outgoing, {
                'type': 'response_error', 'request_id': request_id, 'category': 'synthesis_failed',
            })


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    try:
        serve(args.root, sys.stdin.buffer, sys.stdout.buffer)
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
