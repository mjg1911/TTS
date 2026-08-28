# Phase 5 Task 1 Implementer Report

## Status

Implemented the Task 1 brief exactly and committed the scoped changes.

## Files changed

- `setup.py`
- `script/piper_tray_entry.py`
- `tests/test_core_compatibility.py`
- `tests/windows_tray/test_packaging_contract.py`

## Implementation

- Added the isolated `windows-tray-build` optional extra containing only `pyinstaller>=6,<7`.
- Preserved the existing `windows-tray` runtime extra, `http` extra, core install requirements, and both console entry points.
- Added the minimal packaging launcher that delegates to `piper.windows_tray.__main__.main()` and exits with its return value.
- Added static packaging contract tests for the launcher, isolated build dependency, preserved extras, and preserved entry points.
- Added a core compatibility test proving `piper` can expose `PiperVoice` and `SynthesisConfig` without importing `pystray` or Pillow modules.

## Self-review

- Confirmed only the four Task 1 implementation/test files were staged and committed.
- Confirmed PyInstaller was not added to `install_requires`, `windows-tray`, `dev`, or `http`.
- Confirmed the launcher does not import `app.run_app()` directly or add packaging-specific behavior.
- Confirmed `git diff HEAD^ HEAD --check` passed after the commit.
- Existing unrelated untracked artifacts were not modified or removed.

## Test commands and results

1. `pytest tests/windows_tray/test_packaging_contract.py tests/test_core_compatibility.py -v`

   Result: unavailable. PowerShell reported that `pytest` is not recognized.

2. `.venv\\Scripts\\python.exe -m pytest tests/windows_tray/test_packaging_contract.py tests/test_core_compatibility.py -v`

   Result: unavailable. The `.venv` launcher failed because it targets the missing executable `C:\\Users\\mhoem\\AppData\\Local\\Programs\\Python\\Python312\\python.exe`.

3. `python -m piper --help`

   Result: unavailable. PowerShell reported that `python` is not recognized.

4. `.venv\\Scripts\\python.exe -m piper --help`

   Result: unavailable for the same missing Python 3.12 executable.

5. `git diff HEAD^ HEAD --check`

   Result: passed with no whitespace errors.

6. `git status --short -- setup.py script/piper_tray_entry.py tests/test_core_compatibility.py tests/windows_tray/test_packaging_contract.py`

   Result: clean after commit.

## Commit

- `90b3b2f build: add isolated windows tray packaging entrypoint`

## Concerns

- The focused pytest tests and `python -m piper --help` could not execute because the system Python/Pytest launchers are unavailable and the repository `.venv` points to a missing Python 3.12 executable.
- No Windows-specific or runtime packaging test was in scope for Task 1; those remain for later Phase 5 tasks.

## Review Fix Report

### Status

Addressed both Important/P2 findings from the Task 1 review.

### Fixes

- `tests/test_core_compatibility.py` now imports `piper` in a fresh subprocess and asserts that no `pystray` or `PIL` module is present in that isolated interpreter. The subprocess uses the checkout's `src` directory and preserves the parent environment.
- `tests/windows_tray/test_packaging_contract.py` now parses the `setup()` call with `ast` and verifies the exact `windows-tray-build` contents, the unchanged `windows-tray` runtime contents, and that any PyInstaller dependency is absent from `install_requires`, `dev`, `windows-tray`, and `http`.
- Existing launcher, console entry point, and HTTP-extra contract assertions remain in place.

### Changed files

- `tests/test_core_compatibility.py`
- `tests/windows_tray/test_packaging_contract.py`
- `.superpowers/sdd/phase5-task-1-report.md`

### Verification commands and exact results

1. `pytest tests/windows_tray/test_packaging_contract.py tests/test_core_compatibility.py -v`

   Result: unavailable. PowerShell reported: `The term 'pytest' is not recognized as a name of a cmdlet, function, script file, or executable program.`

2. `python -m pytest tests/windows_tray/test_packaging_contract.py tests/test_core_compatibility.py -v`

   Result: unavailable. PowerShell reported: `The term 'python' is not recognized as a name of a cmdlet, function, script file, or executable program.`

3. `.venv\\Scripts\\python.exe -m pytest tests/windows_tray/test_packaging_contract.py tests/test_core_compatibility.py -v`

   Result: unavailable. The launcher reported: `Unable to create process using '"C:\\Users\\mhoem\\AppData\\Local\\Programs\\Python\\Python312\\python.exe" -m pytest tests/windows_tray/test_packaging_contract.py tests/test_core_compatibility.py -v'` and returned exit code `101`.

4. `.venv\\Scripts\\python.exe -m piper --help`

   Result: unavailable. The launcher reported: `Unable to create process using '"C:\\Users\\mhoem\\AppData\\Local\\Programs\\Python\\Python312\\python.exe" -m piper --help'` and returned exit code `101`.

5. `git diff --check`

   Result: passed with no whitespace errors.
