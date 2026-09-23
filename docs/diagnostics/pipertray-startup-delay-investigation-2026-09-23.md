# PiperTray startup delay investigation

**Date:** 2026-09-23
**Scope:** Read-only investigation of the Windows PiperTray executable startup path. No application code was changed and the executable was not launched during this investigation.

## Summary

The current repository configuration and the local `dist/PiperTray` artifact use a PyInstaller **one-folder** build. Repeated extraction of a roughly 1 GB one-file executable is therefore not a good explanation for startup delays in this build.

The application does substantial work synchronously before it starts the tray icon. The strongest code-level contributors are:

1. Piper loads its configured ONNX voice and constructs an ONNX Runtime inference session on every launch, even when Kokoro is selected.
2. Startup unconditionally verifies the Kokoro installation. When bundled or installed Kokoro assets exist, verification hashes every manifest-listed file and walks the tree to compare the complete file list. This is repeated on each launch.
3. When settings select Kokoro, startup launches the worker and waits synchronously for the worker to import its runtime and load the Kokoro model on CPU. The client permits up to 60 seconds for this initialization.
4. The tray icon is not started until after these operations, so slow startup has no visible progress indicator and looks like the executable did not respond.

These findings identify blocking work in the startup path, but do not establish how many seconds each operation takes on the affected machine. A short timing trace is needed to rank the costs there.

## Evidence from the startup path

### Piper ONNX voice is loaded before tray startup

`run_app()` calls `_load_configured_voice()` before preparing Kokoro or starting the tray. This happens regardless of the selected speech engine. The helper calls `PiperVoice.load()`, which constructs `onnxruntime.InferenceSession` synchronously. The configured voice is loaded again when Piper is prepared after a voice change.

References:

- `src/piper/windows_tray/app.py:281-283` — initial configured voice load.
- `src/piper/windows_tray/app.py:310-319` — Kokoro preparation follows that Piper load; Piper candidates also load synchronously.
- `src/piper/windows_tray/app.py:439-440` — tray startup occurs later.
- `src/piper/voice.py:191-200` — `PiperVoice.load()` creates the ONNX Runtime session.

### Kokoro verification is on the unconditional launch path

`_prepare_kokoro_installation()` is called on every normal startup, before checking whether the selected engine is Kokoro. With a bundled payload, `ensure_bundled_kokoro_payload()` verifies the bundle, then verifies an existing installation if present. If the manifests differ or the installation is missing, it copies the payload and verifies the temporary and installed trees. `verify_kokoro_installation()` hashes each listed file and recursively checks the full file inventory.

References:

- `src/piper/windows_tray/app.py:82-91` — bundled or installed payload preparation.
- `src/piper/windows_tray/app.py:310-312` — unconditional call during startup.
- `src/piper/windows_tray/kokoro_payload.py:50-75` — bundle verification, install check, and first-install/update copy path.
- `src/piper/kokoro_assets.py:44-49,66-85,130-136` — per-file SHA-256 hashing and full-tree inventory check.

Impact depends on the release and user installation. If Kokoro assets are absent, the missing-installation path should fail quickly. If the package or user profile contains the complete Kokoro payload, repeated hashing can cause substantial disk I/O even when Piper is selected. First launch or payload replacement also copies the payload before the app becomes ready.

### Kokoro selection blocks startup while its model loads

When settings select Kokoro, the app calls `backend_manager.prepare()` before creating and starting the tray. That path calls `KokoroWorkerClient.ensure_ready()` inline. The client waits for a worker handshake and then a ready response, with a 60-second initialization timeout. The worker verifies the install, imports spaCy and Kokoro, constructs `KModel`, and moves it to CPU before sending `ready`.

References:

- `src/piper/windows_tray/app.py:325-346` — synchronous worker preparation during app startup.
- `src/piper/windows_tray/kokoro_client.py:42-43,167-220` — 5-second handshake and 60-second initialization waits.
- `src/piper/kokoro_worker/main.py:110-121` — verification and runtime initialization before `ready`.
- `src/piper/kokoro_worker/runtime.py:17-33` — spaCy/Kokoro imports and CPU model load.
- `src/piper/windows_tray/app.py:439-440` — tray starts after initialization.

The existing Kokoro switch-freeze report also documents the same synchronous readiness wait when switching engines from Settings. This startup path is the launch-time counterpart.

## Packaging and local artifact check

The spec uses `EXE(..., exclude_binaries=True)` followed by `COLLECT(...)`, which is PyInstaller's one-folder layout. The local `dist/PiperTray` artifact matches that layout:

- `PiperTray.exe`: 73,096,720 bytes (about 69.7 MiB).
- `_internal`: 7,693 files totaling 778,028,136 bytes (about 741.9 MiB).
- Entire folder: 851,124,856 bytes (about 811.7 MiB).

The largest local support directories include `torch` (about 383 MB), `spacy` (about 94 MB), `transformers` (about 46 MB), and `piper` (about 45 MB). This is a large distribution and may amplify cold disk reads or Windows security scanning, but those effects were not measured. The inspected local artifact did not expose a top-level `_internal/kokoro_payload` directory; it may not be the same release build as the affected user's executable. Confirm the exact artifact/release configuration before attributing its startup time to bundled Kokoro assets.

References:

- `script/piper_tray.spec:49-68` — one-folder `EXE` and `COLLECT` packaging.
- `script/piper_tray_installer.iss:23` — installer copies the folder tree recursively.

## Recommended diagnostic capture

Add temporary timing markers (or use a profiler) around these existing boundaries, and record a monotonic elapsed time for each:

1. Process entry to `main()`.
2. Single-instance acquisition and settings load.
3. Tk root construction.
4. `_load_configured_voice()` / `PiperVoice.load()`.
5. `_prepare_kokoro_installation()` including bundle verification or copying.
6. Kokoro worker launch through its `ready` response, if Kokoro is selected.
7. `tray.start()` and the first `Piper tray runtime ready` log entry.

Capture cold and warm launches on the affected machine for both Piper and Kokoro settings. For a release with Kokoro assets, compare first launch with later launches. If code timings do not account for the observed delay, use Windows Performance Recorder or Process Monitor to check disk reads and Microsoft Defender scanning of the executable and `_internal` tree.

## Implemented startup timing fields

The evidence and recommendations above describe the startup path before the responsive-startup change. In the current implementation, Piper-selected startup skips Kokoro asset preparation, while Kokoro asset preparation and worker readiness run after tray/hotkey startup in the background. The timing fields below describe the current implementation.

PiperTray now writes independent elapsed-time records through the application logger. Each record uses the `startup` event prefix, a `stage` name, and a `duration_seconds` value (formatted to three decimal places):

| Stage | Log fields | Interval measured |
| --- | --- | --- |
| Configured Piper voice load | `startup stage=piper_voice_load duration_seconds=...` | Only the `_load_configured_voice()` call, ending on success or failure. It excludes voice selection UI and settings persistence. |
| First-run selected voice load | `startup stage=piper_voice_selection_load duration_seconds=...` | Only the `load_voice_candidate()` call after the user selects a replacement voice. Emitted only on the first-run selection path. |
| Kokoro asset preparation | `startup stage=kokoro_asset_preparation duration_seconds=...` | Verification or bundled-payload preparation performed for a Kokoro-selected launch. |
| Kokoro worker readiness | `startup stage=kokoro_worker_readiness duration_seconds=...` | Worker launch/readiness, through the worker's ready response or startup failure. |
| Tray and hotkey readiness | `startup stage=tray_hotkey_ready duration_seconds=...` | Tray start and successful hotkey registration. This event is emitted only when both calls return successfully. |
| Tray hotkey registration failure | `startup stage=tray_hotkey_failed duration_seconds=... error_type=...` | Tray start and hotkey registration through a handled `OSError` or `ValueError`; includes the exception class name and does not claim readiness. |

The Piper and tray/hotkey records are logged as fixed stage names. The tray failure event also includes `error_type`; Kokoro's two records use the same `startup stage=%s duration_seconds=%.3f` logger format with the stage name supplied as a field. Durations time only the stated PiperTray calls and do not separately measure or attribute Windows Defender scanning, cold disk reads, OS scheduling, or delays caused by other processes. External activity can affect a call's elapsed time, but these records cannot isolate that contribution. Use Windows Performance Recorder or Process Monitor when external I/O or security scanning needs to be measured.

## Assessment and limits

The pre-change source confirmed that expensive model and integrity work ran inline before the tray started. Those paths were the leading hypotheses for application-level delay at the time. Exact attribution and time contribution remain unconfirmed because the original investigation did not launch the affected executable, collect its startup log, or profile the affected machine. The local `dist/PiperTray` artifact is evidence about this checkout only; it may differ from the user's installed release.

No tests were run during the original read-only investigation. Task 5 verification results are recorded separately in `.superpowers/sdd/responsive-startup-task-5-report.md`.
