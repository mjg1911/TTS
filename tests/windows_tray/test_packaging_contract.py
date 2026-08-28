from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_packaging_launcher_delegates_to_real_tray_entrypoint() -> None:
    text = (ROOT / "script" / "piper_tray_entry.py").read_text(encoding="utf-8")
    assert "from piper.windows_tray.__main__ import main" in text
    assert "SystemExit(main())" in text


def test_build_extra_contains_pyinstaller_without_changing_tray_runtime_extra() -> None:
    text = (ROOT / "setup.py").read_text(encoding="utf-8")
    assert '"windows-tray-build"' in text
    assert '"pyinstaller>=6,<7"' in text.lower()
    assert '"windows-tray"' in text
    assert '"pystray>=0.19.5,<1"' in text
    assert '"Pillow>=10,<12"' in text


def test_core_entrypoints_and_http_extra_are_preserved() -> None:
    text = (ROOT / "setup.py").read_text(encoding="utf-8")
    assert '"piper = piper.__main__:main"' in text
    assert '"piper-tray = piper.windows_tray.__main__:main"' in text
    assert '"http"' in text
    assert '"flask>=3,<4"' in text
