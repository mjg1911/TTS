# Phase 4 Task 1 Report: Windows power-broadcast listener

## Status

DONE_WITH_CONCERNS

## Implementation

Added `src/piper/windows_tray/power_events.py` with:

- Canonical `PBT_APMRESUMEAUTOMATIC` classification through `is_resume_event()`.
- A ctypes Win32 adapter for an invisible top-level window created with `parent=None`.
- `WM_POWERBROADCAST` handling that invokes the supplied callback only for the canonical automatic-resume event.
- `WM_DESTROY` to `PostQuitMessage(0)`, default handling for `WM_CLOSE`, message-loop cleanup, and class unregistration.
- A daemon-thread `PowerBroadcastListener` with startup readiness/error propagation, bounded joins, and idempotent stop behavior.

Added `tests/windows_tray/test_power_events.py` with the required canonical-event, callback-delivery, and idempotent-stop tests using `FakePowerApi`.

## TDD evidence

### RED

Ran:

```text
pytest tests/windows_tray/test_power_events.py -v
```

The command could not start because `pytest` is not available on PATH. Retrying through the repository environment also failed before test collection:

```text
Unable to create process using '"C:\Users\mhoem\AppData\Local\Programs\Python\Python312\python.exe" "C:\PrOgram project\Piper\.venv\Scripts\pytest.exe" tests/windows_tray/test_power_events.py -v'
```

The configured Python 3.12 interpreter is missing, so the required missing-module RED assertion could not be observed.

### GREEN

The focused pytest run could not be executed for the same broken-environment reason. The required compile command was also attempted through the repository environment:

```text
Unable to create process using '"C:\Users\mhoem\AppData\Local\Programs\Python\Python312\python.exe" -m py_compile src/piper/windows_tray/power_events.py'
```

No Python runtime was available for executable verification.

## Static verification and self-review

- Reviewed the complete new module against the Task 1 plan.
- Confirmed the parent argument in `CreateWindowExW` is `None`, with no `HWND_MESSAGE` usage.
- Confirmed only `PBT_APMRESUMEAUTOMATIC` invokes the callback.
- Confirmed the original implementation passed `WM_CLOSE` to `DefWindowProcW`; `WM_DESTROY` posted quit and class cleanup ran in `finally`.
- Confirmed the listener uses a daemon thread, readiness event, startup error propagation, idempotent start/stop, close posting, and a one-second join timeout.
- `git diff --cached --check` passed before commit.

## Files changed

- `src/piper/windows_tray/power_events.py`
- `tests/windows_tray/test_power_events.py`

## Commit

`62767d5 feat: listen for windows resume events`

## Concerns

The repository Python environment is broken: the `.venv` launchers reference the missing `C:\Users\mhoem\AppData\Local\Programs\Python\Python312\python.exe`. Focused tests and `py_compile` therefore remain unverified at runtime; they should be rerun after restoring Python 3.12.

## Fix review findings

### Changes

- Updated `src/piper/windows_tray/power_events.py` to configure Win32 `DestroyWindow` and explicitly handle `WM_CLOSE` by destroying the hidden window and returning `0`.
- Added `_make_wndproc()` so the native shutdown path is directly testable.
- Extended `tests/windows_tray/test_power_events.py` with focused assertions for `WM_CLOSE -> DestroyWindow(hwnd)` and `WM_DESTROY -> PostQuitMessage(0)` while retaining the existing listener lifecycle tests.

### Verification

Attempted:

```text
pytest tests/windows_tray/test_power_events.py -v
```

Result: blocked before collection because `pytest` is not recognized on PATH.

Attempted runtime discovery with `python --version`, `py --version`, and `.venv\\Scripts\\python.exe --version`.

Result: no system Python launcher is available; the repository launcher fails with:

```text
Unable to create process using '"C:\\Users\\mhoem\\AppData\\Local\\Programs\\Python\\Python312\\python.exe" --version'
```

The focused test suite and `py_compile` remain runtime-unverified until that Python 3.12 installation is restored. `git diff --check` passed.
