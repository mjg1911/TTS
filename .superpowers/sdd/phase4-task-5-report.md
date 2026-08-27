# Windows Tray TTS Phase 4 — Task 5 Report

## Status

Task 5, “Recover serialized controller state after Windows resume,” is implemented and committed on the current `Phase-4` branch.

## TDD evidence

1. Added `tests/windows_tray/test_resume_recovery.py` with the four plan-prescribed controller behaviors:
   - active speech cancellation and generation invalidation;
   - idle resume recovery;
   - stale capture invalidation;
   - hotkey conflict recovery without shutdown.
2. Ran the prescribed RED command:
   `pytest tests/windows_tray/test_resume_recovery.py -v`
3. RED was observed at the environment command layer because the normal `pytest` executable is not on PATH:
   `pytest: The term 'pytest' is not recognized as a name of a cmdlet, function, script file, or executable program.`
4. Implemented the minimum production changes.
5. Ran the focused GREEN suite with the bundled Python runtime, `PYTHONPATH=src`, and a workspace-local pytest temp directory:
   `python -m pytest --basetemp .pytest-tmp-task5 tests/windows_tray/test_resume_recovery.py tests/windows_tray/test_hotkey_service.py tests/windows_tray/test_app_foundation.py -q`
   Result: `41 passed in 0.20s`.

## Implemented files

- `src/piper/windows_tray/commands.py`
  - Added `CommandKind.SYSTEM_RESUME`.
- `src/piper/windows_tray/controller.py`
  - Added the `ensure_tray_visible` runtime callback.
  - Added serialized `_recover_from_resume()` handling.
  - Invalidates in-flight capture generations and cancels active speech before restoring resources.
  - Refreshes tray visibility and invokes existing `HotkeyManager.reregister()` once per resume.
  - Reports hotkey conflicts through the stable user-facing policy message and logs safe resume context.
  - Restored `drain_once()` to queue draining only.
- `src/piper/windows_tray/app.py`
  - Wires `TrayIcon.ensure_visible` into the controller.
  - Starts `PowerBroadcastListener` with a callback that only enqueues `SYSTEM_RESUME`.
  - Adds idempotent, privacy-safe power-listener cleanup, including early-failure cleanup.
- `tests/windows_tray/test_resume_recovery.py`
  - Added controller resume regression coverage.
- `tests/windows_tray/test_app_foundation.py`
  - Added power-listener enqueue/cleanup regression coverage.
  - Updated stale tray fakes to exercise the existing restartable tray lifecycle.

## Verification results

- Focused resume/hotkey/app suite: PASS — `41 passed`.
- `python -m compileall -q src/piper/windows_tray`: PASS — exit code `0`.
- `git diff --check`: PASS — exit code `0`.
- No Phase 4 Task 5 production change modified `HotkeyManager`.

## Self-review

- One resume callback produces one queued canonical `SYSTEM_RESUME` command.
- The power listener callback does not mutate controller state.
- Resume recovery is serialized through `Controller.handle()`.
- Capture and speech generations prevent pre-resume work from producing new speech.
- Tray recovery is delegated through `TrayIcon.ensure_visible()`.
- Hotkey re-registration uses the existing boolean-returning interface and preserves process liveness on conflict.
- Power listener cleanup is idempotent and runs from the common `finally` path.
- Existing Phase 3 interfaces were preserved; `HotkeyManager.reregister()` was not changed.

## Runtime blocker

Python is available through the bundled workspace runtime at
`C:\Users\mhoem\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`.
The system `python` and `pytest` commands are unavailable on PATH, and pytest’s default temp root is permission-restricted. Verification therefore used the bundled Python runtime, `PYTHONPATH=src`, and `.pytest-tmp-task5` under the repository. No Python runtime blocker remains for the completed focused verification.
