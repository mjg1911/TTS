# Windows Tray TTS Phase 4 — Task 6 Report

## Status

Task 6, “Make shutdown one deterministic app-owned transition,” is implemented on the current `Phase-4` branch.

## TDD evidence

1. Added `tests/windows_tray/test_shutdown.py` with coordinator ordering, idempotency, failure isolation, cancellation-before-teardown, and duplicate-EXIT coverage.
2. Ran the prescribed RED command with the bundled runtime and `PYTHONPATH=src`; collection failed because `src/piper/windows_tray/lifecycle.py` did not yet exist.
3. Implemented the minimum coordinator/controller changes, then ran the focused GREEN suite.
4. Updated existing controller and app tests for pure queue draining and app-owned teardown.
5. Added a speech-worker timeout diagnostic regression test.

## Implemented files

- `src/piper/windows_tray/lifecycle.py`
  - Added idempotent `TeardownCoordinator`.
  - Runs hotkeys → power → speech → tray → instance → Tk quit.
  - Isolates cleanup failures and always continues to completion.
- `src/piper/windows_tray/controller.py`
  - Removed physical cleanup callbacks and ownership.
  - Restored `drain_once()` to pure queue draining.
  - Added one logical EXIT transition with capture invalidation and speech cancellation before requesting teardown.
- `src/piper/windows_tray/app.py`
  - Owns the single teardown coordinator and all physical cleanup wrappers.
  - Wires `teardown.run` into the controller.
  - Reuses the same coordinator from `finally`.
  - Preserves Tk `destroy()` as a final defensive UI cleanup after coordinator completion.
- `src/piper/windows_tray/speech.py`
  - Retains the five-second daemon-worker join and logs a safe timeout diagnostic without raising.
- `tests/windows_tray/test_shutdown.py`
  - Added Task 6 coordinator and logical-shutdown tests.
- `tests/windows_tray/test_controller_foundation.py`
  - Asserted pure queue draining and removed controller physical-cleanup assertions.
- `tests/windows_tray/test_controller_speech.py`
  - Asserted cancellation and teardown request instead of worker shutdown from controller EXIT.
- `tests/windows_tray/test_speech_worker.py`
  - Added timeout diagnostic coverage.
- `tests/windows_tray/test_app_foundation.py`
  - Updated cleanup ordering expectations for the coordinator-owned Tk quit.

## Verification

- Focused Task 6 suite: PASS — `65 passed in 2.77s`.
- `python -m compileall -q src/piper/windows_tray`: PASS — exit code `0`.
- `git diff --check`: PASS.
- Complete `tests/windows_tray` suite: `169 passed, 6 failed`.

The six full-suite failures are outside Task 6 scope and pre-existing baseline issues:

- `test_clipboard_error_until_timeout_returns_access_error` — capture fake exhausts its scripted reads.
- `test_null_only_clipboard_text_is_not_success[\\x00]` — capture fake exhausts its scripted reads.
- `test_null_only_clipboard_text_is_not_success[\\x00\\x00]` — capture fake exhausts its scripted reads.
- `test_capture_worker_logs_safe_diagnostics_for_unexpected_exception` — existing traceback-frame expectation differs from current safe traceback format.
- `test_tray_stop_and_replay_actions_use_dynamic_enablement` — existing fixture assumes eager icon construction.
- `test_ensure_visible_recovers_when_icon_is_missing` — existing expectation assumes a rebuild path that is not part of Task 6.

No Task 6-focused test failed.

## Self-review

- Logical cancellation occurs before physical teardown is requested.
- Controller no longer calls `SpeechWorker.shutdown()` or owns tray, instance, or Tk cleanup.
- Physical teardown has one app-owned ordered path and is idempotent.
- Cleanup failures do not prevent later resources or completion logging.
- Hotkeys precede instance close, preserving mutex-release ordering.
- Speech shutdown remains bounded at five seconds and reports a timeout diagnostically.
- `finally` reuses the same coordinator; no duplicate physical cleanup sequence remains.
- No packaging, CI, startup-at-login, clipboard restoration, UI Automation, cloud, browser, or playback-window work was added.

## Runtime blocker

The system `python` and `pytest` commands are unavailable on PATH, and pytest’s default temp root is permission-restricted. Verification used:

`C:\Users\mhoem\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`

with `PYTHONPATH=src` and workspace-local `--basetemp .pytest-tmp-task6`. The bundled Python runtime and pytest are functional; there is no blocker for the focused verification. The complete-suite failures are the six baseline failures listed above.
