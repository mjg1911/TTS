# Task 1 Implementation Report

## Status

Implemented Task 1 on the existing `Error-sound-Phase-3` checkout. Native tray notifications are no longer produced for `UserError.NO_TEXT`; visual status remains suppressed for that error. The existing Error sounds policy remains unchanged: enabled submits the approved no-text error speech request, and disabled submits no no-text speech.

## TDD evidence

### RED

Updated the two no-text regression tests first:

- Renamed `test_no_text_capture_uses_native_notification_without_visual_status` to `test_no_text_capture_has_no_native_notification_or_visual_status` and changed its notification assertion to `[]`.
- Renamed `test_no_text_capture_routes_notification_and_spoken_copy_through_policy` to `test_no_text_capture_speaks_error_without_native_notification` and changed its notification assertion to `[]`.
- Preserved the existing speech assertions.

Attempted the mandated focused test command:

`python -m pytest tests/windows_tray/test_controller_capture.py -k no_text -q`

It could not start because PowerShell reported: `python: The term 'python' is not recognized as a name of a cmdlet, function, script file, or executable program.`

Also checked the alternate launcher with `py -m pytest ...`; PowerShell reported that `py` is not recognized. Therefore, a runtime RED failure could not be observed in this environment.

### GREEN

Applied the minimal controller change:

`if error is not UserError.NO_TEXT: self._show_status(message)`

The following `error_sounds` block was left unchanged, including its `message` and `SpeechPurpose.ERROR` behavior.

Attempted the focused test command again after the implementation and later attempted the complete suite command:

`python -m pytest tests/windows_tray -q`

Both are environment-blocked because Python is unavailable on `PATH`; `py` is also unavailable. No pytest result was produced.

## Changed files

- `tests/windows_tray/test_controller_capture.py`: locked down that no-text capture produces no native notification or visual status while preserving enabled Error sounds assertions.
- `src/piper/windows_tray/controller.py`: removed the native notification branch for `UserError.NO_TEXT`; other runtime errors still use visual status.
- `docs/WINDOWS_TRAY.md`: documented no native no-text notification, conditional spoken feedback, and the absence of user-facing no-text feedback when Error sounds is disabled.

## Static checks and self-review

- `git diff --check`: passed with no whitespace errors.
- Searched the scoped files for the old notification wording and test names; the obsolete `_NO_TEXT_NOTIFICATION` constant was removed in the follow-up fix, while the documentation and regression assertions match the new behavior.
- Reviewed the final scoped diff for behavior, test coverage, and documentation only.
- Existing unrelated working-tree changes were not staged or altered.

## Environment concerns

Python and the Python launcher are not available on `PATH`, so the focused and complete Windows tray pytest suites could not run. This prevents runtime confirmation of the RED/GREEN transitions and full-suite status. Available static checks completed successfully.

## Fix: address Task 1 review findings (2026-08-29)

### Changed files

- `tests/windows_tray/test_error_sounds.py`: updated enabled no-text coverage to require no native notification, added explicit disabled Error sounds coverage asserting no no-text speech submission, and removed the obsolete native-notification failure test.
- `tests/windows_tray/test_phase2_capture_flow.py`: updated both no-text capture expectations to require no native notification.
- `tests/windows_tray/test_phase3_replacement_flow.py`: updated replacement-flow coverage to require no native notification while preserving spoken-error assertions.
- `tests/windows_tray/test_controller_capture.py`: removed the obsolete `test_native_notification_failure_uses_injected_logger` test.
- `src/piper/windows_tray/controller.py`: removed the unused `_NO_TEXT_NOTIFICATION` constant.

### Verification

- `python -m pytest tests/windows_tray/test_controller_capture.py -k no_text -q`: blocked; PowerShell reported `python` is not recognized.
- `python -m pytest tests/windows_tray -q`: blocked; PowerShell reported `python` is not recognized.
- `git diff --check`: passed.
- A repository-bundled Python executable was available for fallback verification; focused and complete-suite results are recorded after this section when run.

Fallback results:

- `C:\Users\mhoem\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "import sys; sys.path.insert(0, 'src'); import pytest; raise SystemExit(pytest.main(['tests/windows_tray/test_controller_capture.py', '-k', 'no_text', '-q']))"`: 2 passed, 13 deselected.
- `C:\Users\mhoem\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "import sys; sys.path.insert(0, 'src'); import pytest; raise SystemExit(pytest.main(['tests/windows_tray', '-q']))"`: 233 passed, 40 errors. All errors were setup failures caused by `PermissionError: [WinError 5] Access is denied` while scanning `C:\Users\mhoem\AppData\Local\Temp\pytest-of-mhoem`; no test failures were reported.

### Concerns

- The documentation already reflected the approved no-native-notification behavior, so no documentation change was necessary.
- Existing unrelated working-tree changes were not staged or altered.

## Fix: remove obsolete no-text tray adapter expectations (2026-08-29)

### Changed files

- `tests/windows_tray/test_tray_feedback.py`: replaced the three obsolete `No text selected` adapter inputs with a neutral test notification, preserving generic native delegation, stopped/before-start lifecycle validation, and native-failure propagation.

### Verification

- Full `tests/windows_tray` search: no obsolete standalone `No text selected` notification expectation remains; the only remaining occurrence is the approved full `UserError.NO_TEXT` message in `test_error_policy.py`.
- Bundled Python focused no-text tests: `2 passed, 13 deselected`.
- Bundled Python tray-feedback tests with isolated basetemp: `7 passed`.
- Bundled Python complete `tests/windows_tray` suite with isolated basetemp: `273 passed`.
- `git diff --check`: passed.

### Concerns

- The default pytest temp root raises `PermissionError: [WinError 5] Access is denied` during setup, so isolated workspace basetemp was used for the tray-feedback and complete-suite runs.
- Existing unrelated working-tree changes were not staged or altered.

## Cleanup: final Task 1 review cleanups (2026-08-29)

- Renamed `test_controller_notifies_when_capture_fails_without_replacing_last_text` to `test_capture_failure_preserves_previous_text_without_native_notification`; assertions and behavior are unchanged.
- Updated `review-package-task-1.md` to cover `a4072ee1e832132889589c103025a8f6eca0020f..5f520d8` and the latest verification summary.
- Bundled Python affected-test verification: 2 passed, 13 deselected.
- `git diff --check`: passed.

The default pytest temp-root `WinError 5` remains an environment note; the
latest tray-feedback and complete-suite results are recorded in the review
package. Existing unrelated working-tree changes were not staged or altered.

## Cleanup: final review-artifact consistency (2026-08-29)

- Updated the review package to the complete review range and aligned its verification summary with the latest focused, tray-feedback, and isolated-basetemp complete-suite results.
- Corrected the stale report wording to record that `_NO_TEXT_NOTIFICATION` was removed in the follow-up fix.
