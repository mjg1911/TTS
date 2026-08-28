# Windows Tray TTS Phase 4 — Task 4 Report

## Status

Implemented and committed Task 4, “Centralize recoverable user-facing error policy.”

## TDD evidence

1. Added `tests/windows_tray/test_error_policy.py` before production implementation.
2. Attempted the required red run:

   `pytest tests/windows_tray/test_error_policy.py -v`

   It could not start because `pytest` is not installed or available on PATH.
3. Implemented `errors.py` and the controller/app call-site changes.
4. Added focused capture, synthesis, and playback regression tests.
5. Attempted the required focused suite:

   `pytest tests/windows_tray/test_error_policy.py tests/windows_tray/test_controller_capture.py tests/windows_tray/test_controller_speech.py tests/windows_tray/test_app_foundation.py -q`

   It could not start because `pytest` is not installed or available on PATH.

## Files changed

- `src/piper/windows_tray/errors.py`
- `src/piper/windows_tray/controller.py`
- `src/piper/windows_tray/app.py`
- `tests/windows_tray/test_error_policy.py`
- `tests/windows_tray/test_controller_capture.py`
- `tests/windows_tray/test_controller_speech.py`
- `tests/windows_tray/test_app_foundation.py`

## Implementation summary

- Added `UserError`, `USER_MESSAGES`, and `user_message()` with stable concise messages.
- Classified `ACCESS_ERROR` as `CLIPBOARD`; timeout/empty capture failures use `NO_TEXT`.
- Classified speech failures by `failure_phase`, separating synthesis from playback.
- Centralized failed voice replacement/startup messaging under `VOICE_LOAD`.
- Centralized capture hotkey conflict messaging under `HOTKEY_CONFLICT`.
- Preserved the fixed-F8 cancellation conflict message.
- Preserved process liveness and existing recovery/state behavior.
- Kept diagnostic exception logging separate from user-facing messages.

## Verification

- `git diff --check`: passed.
- `python -m compileall -q src/piper/windows_tray`: blocked; `python` is not installed or available on PATH.
- Focused pytest suite: blocked; `pytest` is not installed or available on PATH.

## Self-review

- All Task 4 required policy categories have stable mappings and tests.
- Capture, speech, voice, and hotkey call sites use the centralized policy.
- Selected text and detailed speech/capture exception messages are not surfaced by these user-facing paths.
- No unrelated APIs or files were modified.
- Runtime verification remains pending until Python and pytest are restored.

## Review-fix evidence

- Invalid hotkey input now maps to centralized `UserError.HOTKEY_INVALID`; the controller no longer displays `str(error)` or any user-derived text.
- Added regression coverage with malicious invalid-hotkey text and asserted that neither the input nor raw exception text reaches the UI.
- Expanded startup candidate voice-load coverage to assert the stable `VOICE_LOAD` message and exclude the raw loader exception detail.
- Attempted covering tests again with:

  `python -m pytest tests/windows_tray/test_error_policy.py tests/windows_tray/test_controller_capture.py tests/windows_tray/test_app_foundation.py -q`

  Blocked exactly because PowerShell reports: `python: The term 'python' is not recognized as a name of a cmdlet, function, script file, or executable program.`
- `Get-Command python, py, pytest -ErrorAction SilentlyContinue` found no configured Python, py launcher, or pytest executable, so compile verification was also unavailable.
- `git diff --check`: passed.
