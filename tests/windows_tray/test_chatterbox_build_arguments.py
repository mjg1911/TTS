"""Verify PowerShell binds the tray builder's shared staging arguments."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_tray_builder_passes_models_as_named_stage_parameters(tmp_path):
    powershell = shutil.which('pwsh') or shutil.which('powershell')
    if powershell is None:
        pytest.skip('PowerShell is unavailable')
    script = (ROOT / 'script' / 'build_windows_tray.ps1').read_text()
    build_call = script.index('& "$Root/script/build_chatterbox_worker.ps1"')
    start = script.index('\n', build_call) + 1
    end = script.index('\n    $env:PIPER_CHATTERBOX_PAYLOAD_DIR', start)
    stage_invocation = script[start:end]
    (tmp_path / 'script').mkdir()
    stub = tmp_path / 'script' / 'stage_chatterbox_payload.ps1'
    stub.write_text('param($Python, $WorkerDir, $OutputDir, $NanoModelDir, $TurboModelDir)\n'
                    '$PSBoundParameters | ConvertTo-Json -Compress\n')
    quoted_root = str(tmp_path).replace("'", "''")
    probe = tmp_path / 'invoke.ps1'
    probe.write_text(f"$Root = '{quoted_root}'\n"
                         "$PayloadDir = 'shared-output'\n$Python = 'python'\n"
                     "$hasNanoModel = $true\n$hasTurboModel = $true\n"
                     "$env:PIPER_NANO_MODEL_DIR = 'nano-model'\n"
                     "$env:PIPER_TURBO_MODEL_DIR = 'turbo-model'\n"
                     + stage_invocation)
    result = subprocess.run([powershell, '-NoProfile', '-File', str(probe)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    bound = json.loads(result.stdout)
    assert bound['WorkerDir'] == 'dist/ChatterboxWorker'
    assert bound['OutputDir'] == 'shared-output'
    assert bound['NanoModelDir'] == 'nano-model'
    assert bound['TurboModelDir'] == 'turbo-model'
    assert bound['Python'] == 'python'


@pytest.mark.parametrize('wrapper', ['build_nano_worker.ps1', 'build_turbo_worker.ps1'])
def test_legacy_build_wrapper_preserves_python_and_skip_install_parameters(tmp_path, wrapper):
    powershell = shutil.which('pwsh') or shutil.which('powershell')
    if powershell is None:
        pytest.skip('PowerShell is unavailable')
    copied_wrapper = tmp_path / wrapper
    copied_wrapper.write_text((ROOT / 'script' / wrapper).read_text())
    builder = tmp_path / 'build_chatterbox_worker.ps1'
    builder.write_text('param([string]$Python, [switch]$SkipInstall)\n'
                       '@{Python=$Python; SkipInstall=[bool]$SkipInstall} | ConvertTo-Json -Compress\n')
    result = subprocess.run([powershell, '-NoProfile', '-File', str(copied_wrapper),
                             '-Python', 'shared-python.exe', '-SkipInstall'],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'Python': 'shared-python.exe', 'SkipInstall': True}
