"""PyInstaller entry point for the isolated Supertonic worker."""

from piper.supertonic_worker.main import main


if __name__ == "__main__":
    raise SystemExit(main())
