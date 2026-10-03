from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_nano_package_is_included_in_distribution():
    setup = (ROOT / 'setup.py').read_text()
    assert '"piper.nano_worker"' in setup
    assert '"piper.kokoro_worker"' not in setup


def test_tray_build_collects_optional_nano_payload():
    spec = (ROOT / 'script/piper_tray.spec').read_text()
    assert 'PIPER_NANO_PAYLOAD_DIR' in spec
    assert 'PIPER_REQUIRE_NANO_PAYLOAD' in spec
    assert 'nano_payload_datas' in spec
    build = (ROOT / 'script/build_windows_tray.ps1').read_text()
    assert 'stage_nano_payload.ps1' in build
    assert 'build_nano_worker.ps1' in build
    assert 'PIPER_REQUIRE_NANO_PAYLOAD' in build


def test_installer_checks_required_nano_payload():
    build = (ROOT / 'script/build_windows_installer.ps1').read_text()
    assert 'PIPER_REQUIRE_NANO_PAYLOAD' in build
    assert 'nano_payload/manifest.json' in build
