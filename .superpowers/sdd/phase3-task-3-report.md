# Phase 3 Task 3 Report

## Status

Implemented Task 3: runtime invalid-hotkey, rebind-conflict, and resume-conflict paths now use the approved runtime error policy. Visual status copy remains exact, enabled error sounds submit the same approved copy with `SpeechPurpose.ERROR`, and persistence rollback failures remain on their existing visual/logging path. Startup app paths were not changed.

## Commits

- `feat: speak approved hotkey errors`

## Test commands and output

- Red phase, before the controller change:
  `C:\Users\mhoem\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest --basetemp=.pytest-basetemp-task3 tests/windows_tray/test_hotkey_rebind.py tests/windows_tray/test_controller_capture.py tests/windows_tray/test_resume_recovery.py -q`
  Result: 4 failed, 27 passed. The failures were the new speech assertions for invalid hotkey, rebind conflict, malicious-input protection, and enabled resume conflict.
- Focused and regression suite:
  `C:\Users\mhoem\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest --basetemp=.pytest-basetemp-task3 tests/windows_tray/test_hotkey_rebind.py tests/windows_tray/test_controller_capture.py tests/windows_tray/test_hotkey_service.py tests/windows_tray/test_resume_recovery.py tests/windows_tray/test_app_foundation.py -q`
  Result: 71 passed, 1 failed. The failure is the pre-existing `test_tk_thread_dispatches_activation_and_exit` expectation in `test_app_foundation.py`; it observes an existing F8 registration-conflict status before the activation status. The foundation file is unchanged.
- Startup visual-only checks included in the regression run passed: invalid persisted hotkey and startup registration conflict did not submit error speech even with error sounds enabled.
- `C:\Users\mhoem\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m compileall -q src/piper/windows_tray`: passed.
- `git diff --check`: passed.

## Self-review

- Changed only the requested controller and three test files, plus this report.
- `_report_runtime_error()` is called for `ValueError` from parsing, failed runtime `rebind()`, and failed resume `reregister()` after auxiliary cancellation and before the existing reregistration completion path.
- Persistence rollback failures remain visual/logging-only and are not routed to spoken runtime errors.
- `tests/windows_tray/test_app_foundation.py` was verified unchanged and remains startup-only for this task.
- The malicious hotkey input is absent from every submitted speech request; only `user_message(UserError.HOTKEY_INVALID)` is submitted.

## Concerns

The prescribed suite is not fully green because of the existing app-foundation expectation described above. No Task 3-scoped test failed after implementation.
