# Piper

Piper is a Windows desktop app that reads selected text aloud from the system tray. It offers Piper for lightweight speech, Chatterbox Nano for expressive English speech on CPU or NVIDIA GPU, and Chatterbox Turbo (350M) for fast English speech on an NVIDIA CUDA GPU.

On startup, choose an engine before its model loads. Closing the choice window exits the app. Piper starts as the fallback while a selected Chatterbox engine loads in the background. If loading fails, Piper remains available; a failed engine change keeps the working engine.

Settings lets you change engines and voices, adjust speech speed and pitch, stop playback, and replay the last selection. These controls work with both Chatterbox engines. Enable Codex monitoring to read completed Codex responses automatically. Normal speech generation uses local models and works offline.

Saved Chatterbox Multilingual V3 selections migrate to Turbo, preserving other preferences. Turbo speaks English only. Saved Kokoro selections migrate to Piper.

## Shared Chatterbox setup

Nano and Turbo share one worker program and one dependency installation. The payload contains `worker/ChatterboxWorker.exe` once, separate `models/nano` and `models/turbo` directories, and an integrity manifest. Switching engines starts the same worker in the selected mode; it does not require a second worker installation. You still need the selected engine's model files.

Install Python 3.11 and Git, then build the shared worker from the repository root:

```powershell
& .\script\build_chatterbox_worker.ps1
```

Stage existing official model files into a fresh output directory:

```powershell
& .\script\stage_chatterbox_payload.ps1 -NanoModelDir 'C:\models\chatterbox-nano' -TurboModelDir 'C:\models\chatterbox-turbo'
```

You can omit either model directory to package just one engine. Model files must match the pinned revisions and hashes in `piper.nano_assets` and `piper.turbo_assets`. The build installs CUDA-enabled Torch, which also supports Nano CPU inference. Build dependency installation needs internet access; normal speech remains offline.

To download both pinned model sets during setup, use `-DownloadNano -DownloadTurbo` instead of model directory arguments:

```powershell
& .\script\stage_chatterbox_payload.ps1 -DownloadNano -DownloadTurbo
```

Either download switch can be used alone. Use a directory or a download switch for each engine, and leave its model-directory environment setting unset when downloading.

For the source app, stage both models into its shared installation directory:

```powershell
& .\script\stage_chatterbox_payload.ps1 -NanoModelDir 'C:\models\chatterbox-nano' -TurboModelDir 'C:\models\chatterbox-turbo' -OutputDir "$env:APPDATA\Piper\Chatterbox"
```

Staging requires a fresh output directory. Use `-OutputDir` to select another directory when rebuilding. Keep reference clips outside the verified payload. Existing per-engine installations remain readable for compatibility, but new builds collect only the shared payload. Replace old staged-payload environment settings with `PIPER_CHATTERBOX_PAYLOAD_DIR`.

To include both models in the Windows app and installer:

```powershell
$env:PIPER_CHATTERBOX_PAYLOAD_DIR = (Resolve-Path '.\build\chatterbox-payload').Path
$env:PIPER_REQUIRE_NANO_PAYLOAD = '1'
$env:PIPER_REQUIRE_TURBO_PAYLOAD = '1'
& .\script\build_windows_tray.ps1
& .\script\build_windows_installer.ps1
```

Alternatively, set `PIPER_NANO_MODEL_DIR` and/or `PIPER_TURBO_MODEL_DIR`; the tray build builds the worker once and stages the selected models together. `PIPER_CHATTERBOX_WORKER_PYTHON` selects the shared build environment or a source-worker Python environment with the pinned worker dependencies. Leave it unset to use the packaged executable at runtime. The old per-engine build commands forward to the shared builder.

## Nano device and custom voice

Nano defaults to CPU. Select GPU under Device in Settings and save to use CUDA when available. If CUDA is unavailable, Nano uses CPU and displays “CUDA unavailable; using CPU.” The saved GPU preference is retained for the next session. NVIDIA hardware and a compatible driver are required for GPU inference.

To add a custom voice, click **Import reference clip** and choose a PCM WAV recording longer than five seconds, preferably clear speech from one speaker. Piper validates the recording and keeps a local copy. Enable the saved/custom voice option and save to apply it. Disable the option and save to return to the default voice; the imported clip remains available. Both the clip and toggle are remembered between sessions. If a clip cannot be imported or prepared, the working voice is preserved.

## Turbo behavior

Turbo requires an NVIDIA CUDA GPU and does not fall back to CPU. If CUDA is unavailable or loading fails, the app shows an error and keeps the working engine. Saved reference clips are shared with Nano. Turbo's delivery-mode selection continues to apply its selected delivery tag during generation. Both engines preserve the upstream audio watermark.
