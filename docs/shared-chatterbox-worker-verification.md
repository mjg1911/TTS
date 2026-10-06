# Shared Chatterbox worker verification

Implemented in the existing `worker` branch, starting from `935c3ab`. No branch switch, push, or release build was performed during this work.

The shared payload contains one `ChatterboxWorker.exe` and dependency tree, with separate pinned Nano and Turbo model directories. Both tray clients select their mode and model directory when launching that executable. Legacy installations remain usable. Missing models permit checking another installation; corrupt payloads reach existing backend error and fallback handling.

## Results

- Full Windows tray and Turbo regression run: **1,009 passed, 2 skipped, 17 failed**.
- Focused shared-worker, assets, discovery, PowerShell argument binding, installer, packaging, Nano/Turbo runtime, and switching regression run: **233 passed, 1 deselected**. The deselected test is the known Turbo fixture failure below.
- All eight PowerShell build/staging scripts and twelve worker/packaging Python sources passed syntax checks.
- Repository whitespace checks passed. The consolidated lock matches both engines' immutable model pins.
- Independent integration review found no remaining production correctness issues after fixes.

## Existing failures

The 17 failures were independently reproduced from the untouched starting commit, using an archived source copy without changing this checkout:

- `tests/windows_tray/test_app_foundation.py`: 1 failure.
- `tests/windows_tray/test_hotkey_recording.py`: 4 failures.
- `tests/windows_tray/test_hotkey_service.py`: 8 failures.
- `tests/windows_tray/test_settings.py`: 3 failures; assertions still expect schema version 2 while the implementation uses version 3.
- `tests/turbo/test_worker.py`: 1 failure; its fake chunk generator rejects the delivery-mode argument already supplied by the original worker.

## Limits

Real CUDA inference and a PyInstaller release build were not exercised. The local test environment lacks the Chatterbox build dependency and the pinned model weights. Packaging recipes, protocol routing, model integrity, and process switching were tested using lightweight fixtures; no model downloads were performed. No actual release-package size measurement is claimed.

Setup and shared build/staging commands are documented in `README.md`.
