# Phase 4 Task 3 — Privacy-Safe Structured Diagnostics

## Status

Implemented in the current `Phase-4` branch.

## TDD evidence

1. Added the required failing tests before production changes:
   - `tests/windows_tray/test_log_redaction.py` verifies capture length logging, selected-text redaction, safe exception type/context, and exception-message redaction.
   - `tests/windows_tray/test_logging_setup.py` verifies configured lines include `version=`.
   - `tests/windows_tray/test_speech_worker.py` verifies synthesis failures report `failure_phase == "synthesis"`.
   - Updated capture-controller expectations to require detail-free routine logs.
2. Attempted the required RED command:

   `pytest tests/windows_tray/test_log_redaction.py tests/windows_tray/test_logging_setup.py tests/windows_tray/test_speech_worker.py tests/windows_tray/test_controller_capture.py -v`

   The command could not start because `pytest` is not recognized by PowerShell.
3. Implemented the minimum production changes required by Task 3.
4. Runtime GREEN verification could not be performed because Python tooling is unavailable; the exact blocker is recorded below.

## Implemented behavior

- Added `app_version()` with a safe `dev` fallback and injected version context into configured log records.
- Added `log_capture_result`, `log_synthesis_result`, and `log_exception_safe`.
- Safe exception logs retain exception type and traceback frame locations while omitting exception messages.
- Capture routine logs contain only fixed outcome/stage data and text length; selected text and `CaptureResult.detail` are not emitted.
- Clipboard access failures are logged at their source with fixed stage names.
- Extended `SpeechEvent` with backward-compatible `failure_phase`.
- Added synthesis timing/outcome diagnostics and safe synthesis/playback failure diagnostics.
- Speech logging never receives `SpeechRequest.text`.

## Files changed

- `src/piper/windows_tray/logging_setup.py`
- `src/piper/windows_tray/capture.py`
- `src/piper/windows_tray/speech.py`
- `src/piper/windows_tray/controller.py`
- `tests/windows_tray/test_logging_setup.py`
- `tests/windows_tray/test_speech_worker.py`
- `tests/windows_tray/test_controller_capture.py`
- `tests/windows_tray/test_log_redaction.py`

## Verification and results

- `git diff --check`: passed.
- Required diagnostics pytest command: blocked before collection; `pytest` is unavailable.
- `python -m compileall -q src/piper/windows_tray`: blocked; `python` is unavailable.
- `where.exe python`, `where.exe py`, and `where.exe pytest`: none found.

## Self-review

- Selected text is not passed to any new logging helper.
- Capture detail remains available in `CaptureResult` for application logic/tests but is not routine-logged.
- Arbitrary speech and clipboard exception messages are omitted from production diagnostics.
- Exception type and traceback frame locations are retained.
- `SpeechEvent` three-argument construction remains valid.
- No hotkey, single-instance, or core API files were modified.
- Runtime test and compile evidence remain pending until a Python 3.12/pytest environment is restored.

## Review follow-up: generic capture exception diagnostics

- Updated `src/piper/windows_tray/controller.py` so the generic capture-worker
  exception fallback calls `log_exception_safe()` with the fixed
  `stage=capture_worker` value before retaining the existing `CaptureResult.detail`
  for application flow.
- Added `test_capture_worker_logs_safe_diagnostics_for_unexpected_exception` to
  verify exception type and traceback frame locations are logged, the fixed stage
  is present, and the exception message is omitted.
- RED attempt:
  `pytest tests/windows_tray/test_controller_capture.py::test_capture_worker_logs_safe_diagnostics_for_unexpected_exception -q`
  was blocked because PowerShell reported that `pytest` is not recognized.
- Covering tests:
  `pytest tests/windows_tray/test_controller_capture.py tests/windows_tray/test_log_redaction.py -q`
  was blocked for the same reason.
- Compile attempts:
  `python -m compileall -q src/piper/windows_tray` and
  `py -3.12 -m compileall -q src/piper/windows_tray` were blocked because
  neither `python` nor `py` is available on PATH.
- `git diff --check`: passed.
