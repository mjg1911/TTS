import json
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


def test_windows_tray_import_does_not_load_kokoro_worker_dependencies():
    code = r"""
import json
import sys
import piper.windows_tray.app
heavy = [name for name in ("kokoro", "torch", "transformers", "misaki", "spacy") if name in sys.modules]
print(json.dumps(heavy))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(result.stdout) == []
