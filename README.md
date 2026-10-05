# Piper

Piper is a Windows desktop app that makes it easy to listen to text while you work. It stays in the system tray, ready to read selected text aloud with a keyboard shortcut.

The app offers three speech engines for different needs. Piper is exceptionally lightweight and quick, making it a good choice for everyday speech with minimal overhead. Chatterbox Nano adds an expressive English default voice that runs locally on your CPU or NVIDIA GPU. Chatterbox Turbo (350M) provides fast English speech and requires an NVIDIA GPU with CUDA.

On startup, click **Piper**, **Chatterbox Nano**, or **Chatterbox Turbo** before any model loads. Closing the choice window exits the app. When starting a Chatterbox engine, Piper loads first as the fallback while the selected engine starts in the background.

Chatterbox Multilingual V3 has been replaced by Turbo. Saved Multilingual selections migrate to Turbo while preserving your other preferences. Turbo speaks English only; the old language, expressiveness, and guidance controls are removed because Turbo does not support them.

Kokoro was removed. If Kokoro was selected in a previous installation, Piper is now selected after upgrade and your other saved preferences are preserved.

Switch between engines and voices to find the sound that suits you. You can also adjust speech speed and pitch, stop playback at any time, and replay the last selection from the tray.

Piper can also read completed Codex responses aloud. Enable Codex monitoring and new answers are spoken using your selected voice, so you can keep up with responses while your attention is elsewhere.

Speech is generated locally using voice models on your computer. Choose your engine in Settings; speed, pitch, Stop, replay, and automatic reading also work with both Chatterbox engines.

## Chatterbox Turbo setup

Select **Chatterbox Turbo (350M)** in Settings. This engine runs exclusively on an NVIDIA CUDA GPU. If CUDA is unavailable or loading fails, the app shows an error and keeps the working engine.

Reference clip import and **Use saved voice** work as for Nano; saved reference clips are shared between both Chatterbox engines. The upstream audio watermark is preserved.

Build a separate worker and stage its pinned Turbo models from the repository root:

```powershell
& .\script\build_turbo_worker.ps1
& .\script\stage_turbo_payload.ps1
```

Setup downloads the pinned model files plus the CUDA worker runtime. Normal speech is offline. To use existing weights, set `PIPER_TURBO_MODEL_DIR`. Staging needs a fresh output directory; pass `-OutputDir` when rebuilding.

For the source app, stage to its installation directory:

```powershell
& .\script\stage_turbo_payload.ps1 -OutputDir "$env:APPDATA\Piper\ChatterboxTurbo"
```

To bundle the payload with the Windows app and installer:

```powershell
$env:PIPER_TURBO_PAYLOAD_DIR = (Resolve-Path '.\build\turbo-payload').Path
$env:PIPER_REQUIRE_TURBO_PAYLOAD = '1'
& .\script\build_windows_tray.ps1
& .\script\build_windows_installer.ps1
```

`PIPER_TURBO_WORKER_PYTHON` selects a dedicated Python environment for worker builds or source-worker development. Leave it unset for the packaged worker. Install Python 3.11, Git, and a compatible NVIDIA driver before building.

## Chatterbox Nano setup

Nano offers its built-in default English voice or a custom voice from a reference clip. It runs in a separate worker so its dependencies do not affect Piper. Normal speech uses local files and does not download models. If Nano is unavailable, the app keeps the current working engine; a failed Nano startup recovers to Piper.

To add a custom voice, select Chatterbox Nano in Settings and click **Import reference clip**. Choose a PCM WAV recording longer than five seconds, preferably clear speech from one speaker. Piper validates the recording and keeps its own local copy, so moving the original file will not break the voice. Enable **Use custom voice** and click **Save changes** to apply it. Turn the toggle off and save to return to the bundled voice; the imported clip stays available. Both the clip selection and toggle are remembered between sessions. If a clip cannot be imported or prepared, the existing working voice is preserved.

Custom voices require the updated Nano worker. When updating an existing installation, rebuild and stage the worker from this branch using the setup commands below.

When Chatterbox Nano is selected in Settings, choose CPU or GPU under Device and
click Save changes. CPU is the default for compatibility. GPU uses CUDA on an available
NVIDIA GPU. The choice is saved between sessions. If CUDA is unavailable in the
worker, speech runs on CPU and the app displays “CUDA unavailable; using CPU.”
The saved GPU preference is retained for the next session.

The worker build installs CUDA-enabled Torch, which also supports CPU inference.
Existing workers built with CPU-only Torch must be rebuilt and their payload
restaged to enable GPU inference. NVIDIA hardware and a compatible driver are
required; the app checks CUDA availability inside the worker environment.

For Windows builds, install Python 3.11 and Git, then build the dedicated worker and stage the pinned official models. Run these commands from the repository root:

```powershell
& .\script\build_nano_worker.ps1
& .\script\stage_nano_payload.ps1
```

These setup steps need an internet connection. The staging script downloads the required model files from the pinned revision of `ResembleAI/chatterbox-nano`. To use existing model files, set `PIPER_NANO_MODEL_DIR` to their directory. The payload contains approximately 2 GB of model files plus the worker runtime. Staging requires a fresh output directory; use `-OutputDir` to choose another directory when rebuilding.

To run the source app, stage into the app's installation directory:

```powershell
& .\script\stage_nano_payload.ps1 -OutputDir "$env:APPDATA\Piper\ChatterboxNano"
```

To include the staged payload in a Windows app build:

```powershell
$env:PIPER_NANO_PAYLOAD_DIR = (Resolve-Path '.\build\nano-payload').Path
$env:PIPER_REQUIRE_NANO_PAYLOAD = '1'
& .\script\build_windows_tray.ps1
& .\script\build_windows_installer.ps1
```

Alternatively, setting `PIPER_NANO_MODEL_DIR` makes the tray build build and stage the Nano worker automatically. `PIPER_NANO_WORKER_PYTHON` selects a dedicated worker Python environment for build scripts and optional source-worker development; leave it unset when testing the packaged worker. Nano preserves the upstream audio watermark. Voice cloning is outside this integration.
