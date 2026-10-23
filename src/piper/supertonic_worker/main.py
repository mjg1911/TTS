"""Framed Supertonic 3 helper process; stdout is reserved for protocol frames."""

import argparse
import contextlib
import sys
from pathlib import Path

from piper.supertonic_assets import inspect_supertonic3_installation
from piper.supertonic_options import ENGINE, validate_device, validate_language, validate_voice
from piper.windows_tray.worker_protocol import (
    encode_audio,
    read_frame,
    validate_initialize,
    validate_synthesize,
    write_frame,
)

from piper.supertonic_worker.runtime import generate_chunks, load_model


def _initialize(root, request):
    fields = {'type', 'manifest_sha256', 'device', 'voice', 'language'}
    if not isinstance(request, dict) or set(request) != fields:
        raise ValueError('invalid Supertonic 3 initialize message')
    validate_initialize({
        'type': request['type'],
        'manifest_sha256': request['manifest_sha256'],
    })
    device = validate_device(request['device'])
    voice = validate_voice(request['voice'])
    language = validate_language(request['language'])
    installation = inspect_supertonic3_installation(root)
    if request['manifest_sha256'] != installation.manifest_sha256:
        raise ValueError('Supertonic 3 manifest identity changed')
    with contextlib.redirect_stdout(sys.stderr):
        model = load_model(installation.model_dir, voice=voice, language=language, device=device)
    return model


def serve(root, incoming, outgoing):
    """Serve one bounded worker session over length-prefixed JSON frames."""
    write_frame(outgoing, {'type': 'hello', 'engine': ENGINE, 'protocol_version': 1})
    try:
        request = read_frame(incoming)
        model = _initialize(root, request)
    except Exception as error:
        print(str(error), file=sys.stderr)
        write_frame(outgoing, {'type': 'startup_error', 'message': str(error)[:1000]})
        return

    write_frame(outgoing, {
        'type': 'ready',
        'sample_rate': model.sample_rate,
        'device': request['device'],
        'device_message': (
            'Supertonic 3 uses GPU (CUDA).' if request['device'] == 'cuda'
            else 'Supertonic 3 uses CPU.'
        ),
    })

    while True:
        try:
            request = read_frame(incoming)
        except EOFError:
            return
        if request.get('type') == 'shutdown':
            return
        validate_synthesize(request)
        if request['voice_id'] != 'default':
            raise ValueError('Supertonic 3 voice must be selected during initialization')

        request_id = request['request_id']
        try:
            with contextlib.redirect_stdout(sys.stderr):
                for audio in generate_chunks(model, request['text']):
                    write_frame(outgoing, {
                        'type': 'audio',
                        'request_id': request_id,
                        'audio': encode_audio(audio),
                    })
            write_frame(outgoing, {'type': 'response_end', 'request_id': request_id})
        except Exception as error:
            print(str(error), file=sys.stderr)
            write_frame(outgoing, {
                'type': 'response_error',
                'request_id': request_id,
                'category': 'synthesis_failed',
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
