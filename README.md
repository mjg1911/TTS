# Piper

Piper is a Windows desktop app that makes it easy to listen to text while you work. It stays in the system tray, ready to read selected text aloud with a keyboard shortcut.

The app offers three speech engines for different needs. Piper is exceptionally lightweight and quick, making it a good choice for everyday speech with minimal overhead. Kokoro offers a more natural, higher-quality sound when you want a richer listening experience. Chatterbox Nano adds an expressive English default voice that runs locally on your CPU or NVIDIA GPU.

Switch between engines and voices to find the sound that suits you. You can also adjust speech speed and pitch, stop playback at any time, and replay the last selection from the tray.

Piper can also read completed Codex responses aloud. Enable Codex monitoring and new answers are spoken using your selected voice, so you can keep up with responses while your attention is elsewhere.

Speech is generated locally using voice models on your computer. Choose your engine in Settings; speed, pitch, Stop, replay, and automatic reading also work with Chatterbox Nano.

## Chatterbox Nano setup

Nano uses its built-in default English voice. It runs in a separate worker so its dependencies do not affect Piper or Kokoro. Normal speech uses local files and does not download models. If Nano is unavailable, the app keeps the current working engine; a failed Nano startup recovers to Piper.

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
