# Windows Tray TTS Phase 5 V3 — Task 3 Report

## Status

Implemented Task 3: the Windows tray developer entry point now accepts an explicit `--debug` flag.

## Changes

- Updated `src/piper/windows_tray/__main__.py` to parse `--debug` after the existing Windows-only guard and pass the result to `run_app(debug=...)`.
- Updated `src/piper/windows_tray/app.py` with the backward-compatible signature `run_app(argv=None, *, debug=False)`.
- Preserved the existing normal-mode logging call shape for Phase 1–4 test doubles and callers.
- Made debug mode force `DEBUG` logging and request console mirroring.
- Updated `src/piper/windows_tray/logging_setup.py` to retain the rotating file handler and add an optional stderr console handler with the same app-version filter and formatter.
- Added entry-point tests for debug-on and default-debug-off behavior.
- Added logging tests for debug console mirroring and normal file-only logging.
- `log_capture_result`, `log_synthesis_result`, and `log_exception_safe` were not changed; selected text is not introduced into debug logging.

## Test summary

Focused command requested by the brief:

```text
pytest tests/windows_tray/test_entrypoint.py tests/windows_tray/test_logging_setup.py -v
```

Result: not executable because `pytest` is not available on PATH.

Focused venv attempt:

```text
.venv\Scripts\pytest.exe tests/windows_tray/test_entrypoint.py tests/windows_tray/test_logging_setup.py -v
```

Result: process creation failed. The venv launcher targets the missing interpreter:

```text
C:\Users\mhoem\AppData\Local\Programs\Python\Python312\python.exe
```

Regression command:

```text
.venv\Scripts\pytest.exe tests/windows_tray -q
```

Result: same missing Python 3.12 interpreter limitation; tests did not start.

Windows help/debug smoke attempts:

```text
.venv\Scripts\python.exe -m piper.windows_tray --help
.venv\Scripts\python.exe -m piper.windows_tray --debug
```

Result: same missing Python 3.12 interpreter limitation; neither command started.

Static repository check:

```text
git diff --check
```

Result: clean. Git emitted only normal LF-to-CRLF working-copy warnings.

## Concerns / limitations

- Python-based verification could not be performed in this environment because the local venv points to an unavailable Python 3.12 installation and no standalone Python or pytest executable is available.
- Windows-only runtime behavior remains pending execution on a Windows host with Python 3.12 and the project environment installed.
- Existing unrelated untracked files and directories were preserved and were not staged.
