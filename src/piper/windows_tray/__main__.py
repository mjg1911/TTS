"""Developer entry point for the Windows tray application."""

from collections.abc import Sequence
import sys
from typing import Optional


def main(argv: Optional[Sequence[str]] = None) -> int:
    if sys.platform != "win32":
        print("piper-tray is supported on Windows only", file=sys.stderr)
        return 2

    from .app import run_app

    return run_app(list(argv or ()))


if __name__ == "__main__":
    raise SystemExit(main())
