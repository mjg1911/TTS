"""Select the Nano or Turbo Chatterbox engine for the shared worker payload."""
import argparse
from pathlib import Path
import sys

from piper.nano_worker.main import serve as serve_nano
from piper.turbo_worker.main import serve as serve_turbo


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--engine', choices=('nano', 'turbo'), required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--model-dir', type=Path, required=True)
    args = parser.parse_args(argv)

    serve = serve_nano if args.engine == 'nano' else serve_turbo
    try:
        serve(
            args.root,
            sys.stdin.buffer,
            sys.stdout.buffer,
            model_dir=args.model_dir,
        )
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
