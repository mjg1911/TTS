# Task 4 Report

## Status

Implemented Task 4 from `.superpowers/sdd/phase1-task-4-brief.md` on top of
Task 3 commit `af2263f`.

Commit created:

`4f1e00c feat: show no selection tray notification`

Only the six files listed in the brief were committed. Existing unrelated
untracked artifacts were preserved.

## Changes

- Added the controller's optional `show_notification` runtime callback and
  stored it as `_show_notification`.
- Routed non-access capture failures (`EMPTY` and `TIMEOUT`) to the native
  notification callback with the exact message `No text selected`.
- Kept `ACCESS_ERROR` on the existing visual status path.
- Caught notification exceptions and logged exactly through the controller
  logger format `Piper tray notification could not be shown: %s`.
- Notification failures do not fall back to status, Tk messagebox, or speech.
- Wired `show_notification=tray.show_notification` during app bootstrap.
- Updated tray fakes and expectations for the callback wiring.
- Added focused regression coverage for native routing, notification failure
  behavior, Tk messagebox non-use, app callback wiring, and replacement-flow
  speech preservation.

## Test summary

Tests were not run. The requested environment does not provide `python`,
`py -3`, or `pytest`; each executable was confirmed unavailable.

The following requested validations were attempted and blocked:

- Focused capture/app/phase-flow pytest suite.
- Phase 1 regression pytest suite.
- Full `tests/windows_tray` plus `tests/test_core_compatibility.py` suite.
- `python -m compileall -q src/piper/windows_tray`.
- `python -m piper --help`.

`git diff --check` completed without whitespace errors. Git reported only its
normal LF/CRLF conversion warnings.

## Self-review

- Commit diff contains only the six requested files.
- No unrelated untracked artifact was staged.
- Clipboard access errors retain their prior visual message path.
- Native notification exceptions are contained and cannot trigger a visual
  fallback.
- No-selection handling does not call the Tk UI or speech worker.
- Existing successful capture, stale completion, and replacement behavior was
  left unchanged.

## Concerns

- Runtime tests and bytecode compilation remain unverified until Python and
  pytest are available.
- Native Windows notification behavior was covered by tests but not exercised
  in this environment.

## Review fix

The replacement-flow regression test was corrected after review. Its
`Controller` now receives `capture=lambda: CaptureResult(CaptureStatus.EMPTY)`,
so the queued completion exercises the native no-selection notification path
instead of the default `ACCESS_ERROR` path. The test continues to assert that
replacement capture does not submit speech and leaves playback stopped.

Validation was attempted again with:

- `pytest tests/windows_tray/test_phase3_replacement_flow.py -q`
- `python -m compileall -q src/piper/windows_tray`

Both commands were blocked because Python and pytest remain unavailable. No
runtime test result is claimed.

## Final review fix wave

The consolidated final-review findings were applied in the shared checkout:

- Extended the `TrayIcon` fallback snapshot with
  `error_sounds_enabled=False`, keeping fallback menu evaluation safe when no
  controller snapshot provider is installed.
- Hardened `TrayIcon.show_notification()` so it requires both an existing icon
  and a running tray, raising exactly `RuntimeError("tray icon is not running")`
  otherwise. Native notification is invoked using the planned positional form
  `notify(message, "Piper")`.
- Routed notification exceptions through the injected controller
  `_log_error` callback, preserving the existing error message and avoiding a
  module-level logger dependency for this controller-owned failure path.
- Updated `_toggle_error_sounds()` to show the exact save-failure status
  `Piper error sound settings could not be saved.` when settings or the save
  callback is unavailable, as well as for save exceptions.
- Moved the `Error sounds` tray item after `Hotkey settings` and before
  `Open log`, and updated the callback-order regression expectation.
- Added regression coverage for the fallback field, notification lifecycle
  guard and native argument style, injected notification logging, and
  unavailable persistence status.
- Removed the accidentally committed
  `.superpowers/sdd/phase1-task-3-report.md` artifact only. Other pre-existing
  unrelated untracked artifacts were not removed or staged.

## Final validation attempt

Runtime validation was attempted after the fix wave:

- `python --version`: blocked; `python` is not recognized.
- `py -3 --version`: blocked; `py` is not recognized.
- Focused pytest suite: blocked; `pytest` is not recognized.
- Full `tests/windows_tray` pytest suite: blocked; `pytest` is not recognized.
- `python -m compileall -q src/piper/windows_tray`: blocked; `python` is not
  recognized.
- `python -m piper --help`: blocked; `python` is not recognized.
- The repository `.venv\Scripts\python.exe` launcher was also attempted for
  version, focused tests, full tray tests, compileall, and module help; each
  failed because it targets the missing executable
  `C:\Users\mhoem\AppData\Local\Programs\Python\Python312\python.exe`.
- `git diff --check`: completed successfully; only normal LF/CRLF conversion
  warnings were emitted.

No Python runtime test, compilation, or CLI result is claimed.

## Final-review concerns

- Runtime behavior remains unverified until a working Python installation and
  pytest are available.
- Native Windows tray notification behavior was not exercised on Windows.
