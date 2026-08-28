# Windows Tray TTS Phase 5 V3 — Task 4 Report

## Status

Implemented and committed Task 4.

Commit: `a40a52b` (`build: add reproducible windows tray build and smoke test`)

## Changes

- Added `script/build_windows_tray.ps1`.
  - Requires Windows.
  - Installs the `windows-tray` and `windows-tray-build` extras.
  - Regenerates the tray icon.
  - Runs the clean PyInstaller build from `script/piper_tray.spec`.
  - Verifies the executable exists and is non-empty.
  - Prints its SHA-256 hash.
  - Does not download or bundle `ffplay.exe`.
- Added `script/smoke_windows_tray.ps1`.
  - Runs `dist/PiperTray.exe` from an isolated temporary working directory.
  - Replaces `APPDATA` and `LOCALAPPDATA` with isolated directories.
  - Removes `PYTHONPATH` for the child process.
  - Verifies the process remains alive and creates the expected log without a bundled voice.
  - Stops the process and restores the caller environment in `finally`.
- Added the two specified packaging contract assertions to `tests/windows_tray/test_packaging_contract.py`.

## Verification

- PowerShell parser check for both new scripts: PASS.
- Static Task 4 contract sweep: PASS.
- `git diff --cached --check`: PASS.
- Existing runtime inspection confirmed the missing-`ffplay` behavior remains unchanged: availability is checked before playback construction, playback failures become `FAILED` events, the controller transitions to `STOPPED`, and it uses `UserError.PLAYBACK`.

## Limitations / concerns

- Python is unavailable in this environment: both `python --version` and `py --version` were not recognized.
- `pytest tests/windows_tray/test_packaging_contract.py -v` could not start because `pytest` was not recognized.
- The Windows build and frozen-runtime smoke scripts were not executed locally because their Python/PyInstaller prerequisites are unavailable. They still require a Windows environment with the declared extras installed.
- The checkout contained numerous pre-existing untracked artifacts; they were not modified or staged.

## Review fix evidence

- Fixed the review finding in `script/smoke_windows_tray.ps1`: guarded temporary-root removal now runs from the `finally` cleanup path, covering both successful and failing smoke runs.
- Kept process termination and caller environment restoration intact; nested `finally` structure ensures restoration and root cleanup still run if process cleanup raises.
- Added a static regression assertion requiring `$SmokeRoot` cleanup inside `finally`.
- PowerShell parser validation for both Task 4 scripts: PASS.
- Static cleanup/restoration contract check: PASS.
- `git diff --check`: PASS.
- Focused regression test red-run attempt was blocked because the available fallback Python executable could not be launched (`Access is denied`). The Windows build and frozen-runtime smoke remain unexecuted in this environment.

## Whole-branch review fix evidence

- Changed `script/smoke_windows_tray.ps1` to allocate `piper-tray-frozen-smoke-<GUID>` beneath the selected temporary base for each run.
- Removed the pre-run deletion of the shared `piper-tray-frozen-smoke` path; `finally` still cleans only the captured `$SmokeRoot`.
- Preserved process termination and restoration of `APPDATA`, `LOCALAPPDATA`, and `PYTHONPATH`.
- Extended `tests/windows_tray/test_packaging_contract.py` to require GUID-based allocation and reject the bare shared-root assignment.
- Static PowerShell validation: PASS (parser, unique-root allocation, no bare shared root, creation ordering, `finally` cleanup, environment restoration, and contract assertions).
- Python and pytest remain unavailable, so the Python contract test and executable smoke were not run locally.
