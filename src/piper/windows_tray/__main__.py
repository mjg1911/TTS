"""Developer entry point for the Windows tray application."""

import argparse
from collections.abc import Sequence
import sys
from typing import Optional


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="piper-tray")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable DEBUG logging and mirror tray logs to the console",
    )
    return parser.parse_args(list(argv))


def main(argv: Optional[Sequence[str]] = None) -> int:
    if sys.platform != "win32":
        print("piper-tray is supported on Windows only", file=sys.stderr)
        return 2

    args = _parse_args(sys.argv[1:] if argv is None else argv)

    from .app import run_app

    return run_app(debug=args.debug)


if __name__ == "__main__":
    raise SystemExit(main())
