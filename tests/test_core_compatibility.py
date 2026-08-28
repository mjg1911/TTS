import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_core_python_api_imports_without_loading_tray_ui_dependencies() -> None:
    script = """
import sys

import piper

assert hasattr(piper, "PiperVoice")
assert hasattr(piper, "SynthesisConfig")
assert not any(
    name == "pystray" or name.startswith("pystray.")
    or name == "PIL" or name.startswith("PIL.")
    for name in sys.modules
), sorted(name for name in sys.modules if name == "pystray" or name.startswith("pystray.") or name == "PIL" or name.startswith("PIL."))
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
