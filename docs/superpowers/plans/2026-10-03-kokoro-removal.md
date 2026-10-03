# Kokoro removal implementation plan

**Goal:** Remove Kokoro on the current branch while preserving Piper and Chatterbox Nano and their shared backend infrastructure.

**Design:** Follow `docs/kokoro-removal-report.md`. Extract shared worker framing/audio, Windows job cleanup, and background startup into neutral modules. Keep BackendManager and speech leases. Migrate historical Kokoro settings to Piper before validation, preserving all other preferences and using atomic persistence. Leave existing user asset directories alone.

## Tasks

- [x] Extract `worker_protocol.py`, `worker_process.py`, and `backend_startup.py`; update Nano imports and retain shared tests for framing, process cleanup and cancellation.
- [x] Remove Kokoro settings and UI fields, choices, verification controls and callbacks. Add regression tests for schema 1/2 and preference-preserving migration.
- [x] Remove Kokoro runtime preparation and startup from `app.py` and `controller.py`; preserve Nano background startup, stale-result disposal, Piper recovery and switching. Adapt shared controller/application tests to Nano.
- [x] Remove Kokoro worker/assets, isolated dependencies and scripts; update tray/installer packaging contracts and current user documentation.
- [x] Run the full applicable test suite, audit active runtime/build references and review all changes. Attempt fresh release builds with installed prerequisites; clearly record any unavailable prerequisites and manual installation/audio checks.

## Verification

Run targeted regression tests before and after their implementations with `.venv/Scripts/python.exe -m pytest`. Run the full Windows tray suite and remaining core tests after integration. Check `git diff --check`, Python compilation, and active source/build references. Preserve unrelated untracked user files and work on `Kokoro-remove`.

## Verified results

- Full repository suite: 837 passed, 2 skipped (FFmpeg unavailable for the pitch/playback integration tests).
- Python compilation and `git diff --check` pass.
- Active source/build references remain only for migration, bounded installer upgrade cleanup and release documentation.
- Real Piper synthesis with the local Alba model: 104448 PCM bytes at 22050 Hz.
- Newly rebuilt Nano worker: offline CPU synthesis produced 3 chunks and 138240 samples at 24000 Hz; its archive contains `worker_protocol` and no Kokoro module.
- Review fixes preserve backend ownership after successful startup result transfer, keep cancellation cleanup for failed results, bound Windows job launch-failure cleanup and remove migration temporary files when atomic replacement fails.
- Installer compilation and clean-install/upgrade execution remain unverified because Inno Setup is unavailable. No system installation was performed.

- Fresh Nano worker build: `build/nano-worker-kokoro-removal-dist/NanoWorker/NanoWorker.exe`.
- Fresh tray build with rebuilt Nano payload: `build/piper-tray-kokoro-removal-nano-dist/PiperTray/PiperTray.exe` (73138338 launcher bytes).
- Independent archive/file inspection confirms the fresh tray and Nano worker contain required neutral shared modules and no Kokoro modules or payload files.
- Existing `dist/PiperTray` was not overwritten. Implementation branch: `Kokoro-remove`.
