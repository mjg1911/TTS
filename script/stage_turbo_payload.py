"""Compatibility command that stages Turbo in the shared payload layout."""
import argparse
from pathlib import Path

from stage_chatterbox_payload import stage_payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-dir", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    stage_payload(
        args.worker_dir,
        args.output,
        turbo_model_dir=args.model_dir,
        download_models=() if args.model_dir else {"turbo"},
    )


if __name__ == "__main__":
    main()
