"""Exercise the installer's shared-payload verification before compilation."""
from pathlib import Path

import pytest

from tests.windows_tray.test_chatterbox_assets import _write_shared_payload


ROOT = Path(__file__).resolve().parents[2]


def _run_installer_verification(monkeypatch, tmp_path, engines=('nano', 'turbo')):
    source, _, _ = _write_shared_payload(tmp_path, monkeypatch, engines=engines)
    output = tmp_path / 'dist' / 'PiperTray' / '_internal' / 'chatterbox_payload'
    output.parent.mkdir(parents=True)
    source.rename(output)
    monkeypatch.chdir(tmp_path)
    script = (ROOT / 'script' / 'build_windows_installer.ps1').read_text()
    verification = script.split("$checkPayload = @'", 1)[1].split("\n'@", 1)[0].lstrip()
    return verification, output


def test_installer_verifies_one_shared_runtime_for_both_required_engines(monkeypatch, tmp_path):
    verification, _ = _run_installer_verification(monkeypatch, tmp_path)
    monkeypatch.setenv('PIPER_REQUIRE_NANO_PAYLOAD', '1')
    monkeypatch.setenv('PIPER_REQUIRE_TURBO_PAYLOAD', '1')
    exec(compile(verification, 'installer-payload-check', 'exec'), {})


def test_installer_rejects_missing_required_turbo_model(monkeypatch, tmp_path):
    verification, _ = _run_installer_verification(monkeypatch, tmp_path, engines=('nano',))
    monkeypatch.setenv('PIPER_REQUIRE_NANO_PAYLOAD', '1')
    monkeypatch.setenv('PIPER_REQUIRE_TURBO_PAYLOAD', '1')
    with pytest.raises(ValueError, match='requires.*turbo'):
        exec(compile(verification, 'installer-payload-check', 'exec'), {})


def test_installer_rejects_corrupted_shared_worker(monkeypatch, tmp_path):
    verification, output = _run_installer_verification(monkeypatch, tmp_path)
    (output / 'worker' / 'ChatterboxWorker.exe').write_bytes(b'corrupt')
    monkeypatch.delenv('PIPER_REQUIRE_NANO_PAYLOAD', raising=False)
    monkeypatch.delenv('PIPER_REQUIRE_TURBO_PAYLOAD', raising=False)
    with pytest.raises(ValueError, match='hash mismatch'):
        exec(compile(verification, 'installer-payload-check', 'exec'), {})
