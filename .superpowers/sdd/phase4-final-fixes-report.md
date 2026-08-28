# Windows Tray TTS Phase 4 — Final Whole-Branch Review Fixes

Date: 2026-08-27
Branch: `Phase-4`

## Changes

- Fixed `TrayIcon.ensure_visible()` so a missing native icon reconciles stale lifecycle state and rebuilds a fresh detached icon while preserving idempotent `start()` behavior.
- Updated the Phase 3 replacement-flow tray fake to exercise intentional lazy icon construction through `start()` before inspecting menu state.
- Updated the safe capture-diagnostic assertion to validate the actual privacy-safe `controller.py` traceback-frame format.
- Made the speech shutdown timeout test attach directly to the speech logger, so it remains valid when logger propagation is disabled or handlers are reconfigured.
- Extended three capture polling fixtures with sufficient repeated sequence/read values to model continued polling through timeout and empty-text retries.

## Verification

Used the available fallback Python 3.13 runtime at `C:\Users\mhoem\AppData\Local\Temp\p\.venv\Scripts\python.exe` with `PYTHONPATH=src` and workspace-local pytest temporary directories.

- Focused review regressions: **18 passed**.
- Complete `tests/windows_tray` suite: **182 passed**.
- `python -m compileall -q src/piper/windows_tray`: passed with no output.
- `git diff --check`: passed; only expected line-ending normalization warnings were emitted.

The repository-local `.venv` remains unusable because its configured Python 3.12 executable is missing; this did not prevent verification with the fallback runtime.

## Changed files

- `src/piper/windows_tray/tray_icon.py`
- `tests/windows_tray/test_capture.py`
- `tests/windows_tray/test_controller_capture.py`
- `tests/windows_tray/test_phase3_replacement_flow.py`
- `tests/windows_tray/test_speech_worker.py`
