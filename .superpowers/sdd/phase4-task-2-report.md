# Windows Tray TTS Phase 4 — Task 2 Report

## Status

Implemented Task 2, “Make the tray icon lifecycle restartable,” on the current Phase-4 branch.

## TDD evidence

1. Added `tests/windows_tray/test_tray_lifecycle.py` before changing production code.
2. Attempted the required RED command:

   ```text
   pytest tests/windows_tray/test_tray_lifecycle.py -v
   ```

   The test runner could not start because `pytest` is unavailable in the environment.
3. Implemented the minimum lifecycle behavior required by the tests:
   - constructor retains inputs and does not build an icon;
   - `running` reports adapter state;
   - `start()` is idempotent and builds/starts on demand;
   - `ensure_visible()` starts only when stopped;
   - `stop()` is idempotent and clears adapter state in a `finally` block;
   - menu command behavior is preserved;
   - `update_menu()` is safe when no icon is running.

## Verification

Attempted commands:

```text
pytest tests/windows_tray/test_tray_lifecycle.py -v
pytest tests/windows_tray/test_tray_lifecycle.py tests/windows_tray/test_app_foundation.py -q
python -m compileall -q src/piper/windows_tray
```

All Python-based verification is blocked by the same environment issue: no `pytest`, `python`, `py`, `python3`, or `uv` executable is available on PATH. The exact initial failure was:

```text
pytest: The term 'pytest' is not recognized as a name of a cmdlet, function, script file, or executable program.
```

`git diff --check` passed with exit code 0.

## Scope

Changed only the Task 2 production module and lifecycle test, plus this report. No packaging or unrelated lifecycle changes were made.

## Concerns

Runtime test and compile verification remain pending until a Python/pytest runtime is restored.
