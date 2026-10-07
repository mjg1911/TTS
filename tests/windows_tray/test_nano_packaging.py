from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def test_worker_entry_does_not_create_bytecode_in_payload(tmp_path):
    """Source-only bundled dependencies must leave manifest inventory unchanged."""
    package = tmp_path / 'piper' / 'chatterbox_worker'
    package.mkdir(parents=True)
    (package.parent / '__init__.py').write_text('')
    (package / '__init__.py').write_text('')
    (package / 'main.py').write_text('def main(): return 0\n')
    entry = (ROOT / 'script/chatterbox_worker_entry.py').read_text()
    environment = os.environ.copy()
    environment.pop('PYTHONDONTWRITEBYTECODE', None)
    result = subprocess.run(
        [sys.executable, '-c', entry], cwd=tmp_path,
        capture_output=True, text=True, env=environment,
    )
    assert result.returncode == 0, result.stderr
    assert not list(tmp_path.rglob('*.pyc'))


def test_shared_chatterbox_worker_package_is_included_in_distribution():
    setup = (ROOT / 'setup.py').read_text()
    assert '"piper.chatterbox_worker"' in setup
    assert '"piper.kokoro_worker"' not in setup


def test_tray_build_collects_and_requires_nano_through_shared_payload():
    spec = (ROOT / 'script/piper_tray.spec').read_text()
    assert 'PIPER_CHATTERBOX_PAYLOAD_DIR' in spec
    assert 'PIPER_REQUIRE_{engine.upper()}_PAYLOAD' in spec
    assert 'chatterbox_payload_datas' in spec
    assert 'inspect_chatterbox_installation' in spec
    assert 'nano_payload_datas' not in spec
    build = (ROOT / 'script/build_windows_tray.ps1').read_text()
    assert 'stage_chatterbox_payload.ps1' in build
    assert 'build_chatterbox_worker.ps1' in build
    assert 'PIPER_REQUIRE_NANO_PAYLOAD' in build


def test_installer_checks_required_nano_payload():
    build = (ROOT / 'script/build_windows_installer.ps1').read_text()
    assert 'PIPER_REQUIRE_NANO_PAYLOAD' in build
    assert 'chatterbox_payload/manifest.json' in build
    assert 'inspect_chatterbox_installation' in build
