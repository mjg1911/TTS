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
    assert extras["windows-tray"] == [
        "pystray>=0.19.5,<1",
        "Pillow>=10,<12",
        "websockets>=15,<16",
    ]
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


def test_spec_includes_compiled_espeak_bridge_extension() -> None:
    text = (ROOT / "script" / "piper_tray.spec").read_text(encoding="utf-8")

    assert "glob(\"*.pyd\")" in text
    assert "piper_extensions" in text
    assert "binaries=piper_binaries + piper_extensions" in text


def test_spec_includes_tkinter_for_lazy_tray_ui_import() -> None:
    text = (ROOT / "script" / "piper_tray.spec").read_text(encoding="utf-8")

    assert '"tkinter"' in text
    assert '"tkinter.filedialog"' in text
    assert '"tkinter.messagebox"' in text
    assert '"tkinter.simpledialog"' in text


def test_spec_places_tcl_tk_data_where_pyinstaller_runtime_hook_expects_it() -> None:
    text = (ROOT / "script" / "piper_tray.spec").read_text(encoding="utf-8")

    assert '"_tcl_data"' in text
    assert '"_tk_data"' in text


def test_spec_builds_one_folder_distribution() -> None:
    text = (ROOT / "script" / "piper_tray.spec").read_text(encoding="utf-8")
    assert "exclude_binaries=True" in text
    assert "coll = COLLECT(" in text
    assert "a.binaries," in text
    assert "a.datas," in text
    assert 'name="PiperTray"' in text
    assert "nano_payload_datas" in text
    assert "kokoro" not in text.lower()


def test_ffmpeg_and_ffplay_remain_external_to_frozen_bundle() -> None:
    text = (ROOT / "script" / "piper_tray.spec").read_text(encoding="utf-8").lower()

    assert "ffmpeg" not in text
    assert "ffplay" not in text


def test_spec_resolves_paths_from_repository_root() -> None:
    text = (ROOT / "script" / "piper_tray.spec").read_text(encoding="utf-8")

    assert "SPEC_DIR = Path(SPECPATH)" in text
    assert 'SPEC_DIR / "piper_tray_entry.py"' in text
    assert 'ROOT / "src"' in text
    assert 'ROOT / "build" / "piper-tray" / "piper-tray.ico"' in text


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


def test_windows_build_script_fails_if_espeak_bridge_was_not_built() -> None:
    text = (ROOT / "script" / "build_windows_tray.ps1").read_text(
        encoding="utf-8"
    )

    assert "espeakbridge*.pyd" in text
    assert "espeakbridge.pyd was not built" in text


def test_windows_build_script_builds_python_extension_before_packaging() -> None:
    text = (ROOT / "script" / "build_windows_tray.ps1").read_text(
        encoding="utf-8"
    )

    assert "python setup.py build_ext --inplace" in text


def test_python_extension_cmake_quotes_external_include_path() -> None:
    text = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")

    assert 'CMAKE_C_FLAGS=-D_FILE_OFFSET_BITS=64 -I\\"${ESPEAKNG_BUILD_DIR}' in text
    assert 'CMAKE_CXX_FLAGS=-D_FILE_OFFSET_BITS=64 -I\\"${ESPEAKNG_BUILD_DIR}' in text


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


def test_frozen_smoke_script_provisions_voice_and_waits_for_runtime_readiness() -> None:
    text = (ROOT / "script" / "smoke_windows_tray.ps1").read_text(
        encoding="utf-8"
    )

    assert "PIPER_SMOKE_VOICE_DIR" in text
    assert "en_GB-alba-medium.onnx" in text
    assert "en_GB-alba-medium.onnx.json" in text
    assert "Copy-Item $VoiceModel $SmokeVoice" in text
    assert 'voice = "en_GB-alba-medium"' in text
    assert 'Piper tray runtime ready' in text
    assert "$Deadline = [DateTime]::UtcNow.AddSeconds(60)" in text
    assert "Frozen runtime did not report tray readiness" in text


def test_frozen_smoke_script_cleans_temporary_root_in_finally() -> None:
    text = (ROOT / "script" / "smoke_windows_tray.ps1").read_text(
        encoding="utf-8"
    )
    finally_block = text.split("finally {", 1)[1]

    assert "Test-Path $SmokeRoot" in finally_block
    assert "Remove-Item -Recurse -Force $SmokeRoot" in finally_block


def test_frozen_smoke_script_waits_for_process_and_retries_cleanup() -> None:
    text = (ROOT / "script" / "smoke_windows_tray.ps1").read_text(
        encoding="utf-8"
    )
    finally_block = text.split("finally {", 1)[1]

    assert "WaitForExit" in finally_block
    assert "for ($Attempt = 1; $Attempt -le 10; $Attempt++)" in finally_block
    assert "Start-Sleep -Seconds 1" in finally_block
    assert (
        "Remove-Item -Recurse -Force $SmokeRoot -ErrorAction Stop\n"
        "                    $CleanupError = $null\n"
        "                    break"
    ) in finally_block


def test_frozen_smoke_script_terminates_the_full_process_tree() -> None:
    text = (ROOT / "script" / "smoke_windows_tray.ps1").read_text(
        encoding="utf-8"
    )
    finally_block = text.split("finally {", 1)[1]

    assert "taskkill.exe /PID $Process.Id /T /F" in finally_block


def test_frozen_smoke_script_uses_a_unique_temporary_root() -> None:
    text = (ROOT / "script" / "smoke_windows_tray.ps1").read_text(
        encoding="utf-8"
    )

    assert "[System.Guid]::NewGuid().ToString('N')" in text
    assert '$SmokeRoot = Join-Path $BaseTemp "piper-tray-frozen-smoke"' not in text


def test_build_and_smoke_use_one_folder_executable() -> None:
    build = (ROOT / "script" / "build_windows_tray.ps1").read_text(encoding="utf-8")
    smoke = (ROOT / "script" / "smoke_windows_tray.ps1").read_text(encoding="utf-8")
    assert '$DistDir = Join-Path $Root "dist\\PiperTray"' in build
    assert '$Exe = Join-Path $DistDir "PiperTray.exe"' in build
    assert '$Exe = Join-Path $Root "dist\\PiperTray\\PiperTray.exe"' in smoke
    assert "kokoro" not in build.lower()
    assert "kokoro" not in smoke.lower()


def test_kokoro_only_packaging_inputs_are_removed() -> None:
    removed_paths = (
        "requirements/kokoro-worker.in",
        "requirements/kokoro-worker-win-py311.lock",
        "script/accept_windows_kokoro_offline.ps1",
        "script/build_kokoro_worker.ps1",
        "script/kokoro_assets.lock.json",
        "script/kokoro_worker_entry.py",
        "script/kokoro_worker.spec",
        "script/smoke_kokoro_worker_stdio.ps1",
        "script/smoke_windows_kokoro.ps1",
        "script/stage_kokoro_payload.ps1",
        "script/write_kokoro_manifest.py",
    )

    assert all(not (ROOT / path).exists() for path in removed_paths)


def test_current_user_docs_describe_two_engines_and_kokoro_migration() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").lower()

    assert "offers two speech engines" in readme
    assert "kokoro was removed" in readme
    assert "piper is now selected" in readme
    assert "remove kokoro" in changelog


def test_installer_ships_entire_one_folder_tree() -> None:
    builder = (ROOT / "script" / "build_windows_installer.ps1").read_text(encoding="utf-8")
    installer = (ROOT / "script" / "piper_tray_installer.iss").read_text(encoding="utf-8")
    assert '"dist/PiperTray/PiperTray.exe"' in builder
    assert "kokoro" not in builder.lower()
    assert "nano_payload/manifest.json" in builder
    assert 'Source: "..\\dist\\PiperTray\\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs' in installer


def test_installer_removes_only_the_stale_installed_kokoro_payload() -> None:
    installer = (ROOT / "script" / "piper_tray_installer.iss").read_text(
        encoding="utf-8"
    ).lower()

    assert "[installdelete]" in installer
    assert 'type: filesandordirs; name: "{app}\\_internal\\kokoro_payload"' in installer
    assert '"{localappdata}\\piper\\kokoro"' not in installer
