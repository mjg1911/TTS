"""Turbo packaging keeps the model and isolated worker available offline."""
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def test_turbo_worker_package_is_included_in_distribution():
    setup = (ROOT / 'setup.py').read_text()
    assert '"piper.chatterbox_worker"' in setup
    assert '"piper.multilingual_worker"' not in setup


def test_tray_and_installer_collect_and_require_turbo_payload():
    spec = (ROOT / 'script/piper_tray.spec').read_text()
    build = (ROOT / 'script/build_windows_tray.ps1').read_text()
    installer = (ROOT / 'script/build_windows_installer.ps1').read_text()
    assert 'PIPER_CHATTERBOX_PAYLOAD_DIR' in spec
    assert 'PIPER_REQUIRE_{engine.upper()}_PAYLOAD' in spec
    assert 'chatterbox_payload_datas' in spec
    assert 'inspect_chatterbox_installation' in spec
    assert 'turbo_payload_datas' not in spec
    assert 'stage_chatterbox_payload.ps1' in build
    assert 'build_chatterbox_worker.ps1' in build
    assert 'PIPER_REQUIRE_TURBO_PAYLOAD' in installer
    assert 'chatterbox_payload/manifest.json' in installer
    assert 'inspect_chatterbox_installation' in installer
    assert not any('MULTILINGUAL' in script for script in (spec, build, installer))


def test_turbo_worker_entry_preserves_offline_payload_inventory(tmp_path):
    package = tmp_path / 'piper/chatterbox_worker'
    package.mkdir(parents=True)
    (package.parent / '__init__.py').write_text('')
    (package / '__init__.py').write_text('')
    (package / 'main.py').write_text('def main(): return 0\n')
    entry = (ROOT / 'script/chatterbox_worker_entry.py').read_text()
    environment = os.environ.copy()
    environment.pop('PYTHONDONTWRITEBYTECODE', None)
    result = subprocess.run([sys.executable, '-c', entry], cwd=tmp_path,
                            capture_output=True, text=True, env=environment)
    assert result.returncode == 0, result.stderr
    assert not list(tmp_path.rglob('*.pyc'))
