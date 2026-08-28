import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _setup_call() -> ast.Call:
    tree = ast.parse((ROOT / "setup.py").read_text(encoding="utf-8"))
    return next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "setup"
    )


def _extras_require() -> dict[str, list[str]]:
    setup_call = _setup_call()
    extras = next(keyword.value for keyword in setup_call.keywords if keyword.arg == "extras_require")
    return ast.literal_eval(extras)


def _install_requires() -> list[str]:
    setup_call = _setup_call()
    install_requires = next(
        keyword.value for keyword in setup_call.keywords if keyword.arg == "install_requires"
    )
    return ast.literal_eval(install_requires)


def test_packaging_launcher_delegates_to_real_tray_entrypoint() -> None:
    text = (ROOT / "script" / "piper_tray_entry.py").read_text(encoding="utf-8")
    assert "from piper.windows_tray.__main__ import main" in text
    assert "SystemExit(main())" in text


def test_build_extra_contains_pyinstaller_without_changing_tray_runtime_extra() -> None:
    extras = _extras_require()

    assert extras["windows-tray-build"] == ["pyinstaller>=6,<7"]
    assert extras["windows-tray"] == ["pystray>=0.19.5,<1", "Pillow>=10,<12"]
    assert not any(
        dependency.lower().startswith("pyinstaller")
        for dependency in _install_requires()
    )
    for extra_name in ("dev", "windows-tray", "http"):
        assert not any(
            dependency.lower().startswith("pyinstaller")
            for dependency in extras[extra_name]
        )


def test_core_entrypoints_and_http_extra_are_preserved() -> None:
    text = (ROOT / "setup.py").read_text(encoding="utf-8")
    assert '"piper = piper.__main__:main"' in text
    assert '"piper-tray = piper.windows_tray.__main__:main"' in text
    assert '"http"' in text
    assert '"flask>=3,<4"' in text


def test_spec_is_no_console_and_collects_required_runtime_content() -> None:
    text = (ROOT / "script" / "piper_tray.spec").read_text(encoding="utf-8")
    assert "console=False" in text
    assert 'collect_data_files("piper")' in text
    assert 'collect_dynamic_libs("piper")' in text
    assert 'collect_submodules("pystray")' in text
    assert '"piper.espeakbridge"' in text
    assert 'name="PiperTray"' in text


def test_spec_builds_one_file_executable() -> None:
    text = (ROOT / "script" / "piper_tray.spec").read_text(encoding="utf-8")
    assert "COLLECT(" not in text
    assert "a.binaries" in text
    assert "a.datas" in text


def test_icon_generator_uses_repository_logo_and_expected_target() -> None:
    text = (ROOT / "script" / "make_piper_tray_icon.py").read_text(
        encoding="utf-8"
    )
    assert '"etc" / "logo.png"' in text
    assert '"piper-tray.ico"' in text
    assert 'format="ICO"' in text


def test_windows_build_script_runs_icon_generation_and_pyinstaller() -> None:
    text = (ROOT / "script" / "build_windows_tray.ps1").read_text(
        encoding="utf-8"
    )
    assert "make_piper_tray_icon.py" in text
    assert "PyInstaller" in text
    assert "PiperTray.exe" in text
    assert "Get-FileHash" in text


def test_frozen_smoke_script_uses_clean_environment() -> None:
    text = (ROOT / "script" / "smoke_windows_tray.ps1").read_text(
        encoding="utf-8"
    )
    assert "PiperTray.exe" in text
    assert "APPDATA" in text
    assert "LOCALAPPDATA" in text
    assert "PYTHONPATH" in text
    assert "Start-Process" in text
    assert "HasExited" in text


def test_frozen_smoke_script_cleans_temporary_root_in_finally() -> None:
    text = (ROOT / "script" / "smoke_windows_tray.ps1").read_text(
        encoding="utf-8"
    )
    finally_block = text.split("finally {", 1)[1]

    assert "Test-Path $SmokeRoot" in finally_block
    assert "Remove-Item -Recurse -Force $SmokeRoot" in finally_block


def test_windows_workflow_tests_builds_smokes_and_uploads() -> None:
    text = (ROOT / ".github" / "workflows" / "windows-tray.yml").read_text(
        encoding="utf-8"
    )
    assert "windows-latest" in text
    assert "pytest tests/windows_tray tests/test_core_compatibility.py" in text
    assert "python -m piper --help" in text
    assert "build_windows_tray.ps1" in text
    assert "smoke_windows_tray.ps1" in text
    assert "actions/checkout@v7" in text
    assert "actions/setup-python@v7" in text
    assert "actions/upload-artifact@v7" in text
    assert "if-no-files-found: error" in text
