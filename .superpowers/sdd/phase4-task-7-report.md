# Windows Tray TTS Phase 4 — Task 7 Report

## Status

Task 7, “Lock the Phase 4 reliability contract with cross-feature regressions,” is implemented on the current `Phase-4` branch.

## Scope

Created only:

- `tests/windows_tray/test_reliability_scenarios.py`
- `.superpowers/sdd/phase4-task-7-report.md`

No production implementation, packaging, CI, or Phase 5 manual-acceptance files were changed.

## Scenarios covered

The new test module contains exactly the three plan-specified cross-feature scenarios:

1. A stale capture completion arriving after resume cannot submit speech or populate `last_text`.
2. A resume-time hotkey conflict leaves the controller alive and permits a later clean Exit.
3. Resume cancellation invalidates the active speech generation, and replay submits only the post-resume generation.

## Verification commands and results

The system `python` and `pytest` commands are unavailable on PATH. Verification used the existing fallback Python 3.13.5 environment at `C:\Users\mhoem\AppData\Local\Temp\p\.venv\Scripts\python.exe`, with `PYTHONPATH=src`. Pytest’s default temporary directory is permission-restricted, so suite runs used workspace-local `--basetemp` directories.

### New reliability file

Command:

```text
$env:PYTHONPATH = 'src'; & 'C:\Users\mhoem\AppData\Local\Temp\p\.venv\Scripts\python.exe' -m pytest tests/windows_tray/test_reliability_scenarios.py -v
```

Result: PASS — 3 passed in 1.02s.

### Required existing contract tests

Command:

```text
$env:PYTHONPATH = 'src'; & 'C:\Users\mhoem\AppData\Local\Temp\p\.venv\Scripts\python.exe' -m pytest --basetemp '.pytest-tmp-task7-contract' tests/windows_tray/test_capture.py tests/windows_tray/test_clipboard.py tests/windows_tray/test_hotkey_service.py tests/windows_tray/test_single_instance.py tests/windows_tray/test_voice_manager.py tests/windows_tray/test_phase3_replacement_flow.py -q
```

Result: 48 passed, 4 failed.

The failures are pre-existing baseline issues outside Task 7:

- Three `test_capture.py` fake-clipboard cases exhaust scripted reads during repeated polling.
- `test_phase3_replacement_flow.py::test_tray_stop_and_replay_actions_use_dynamic_enablement` assumes eager tray-icon construction, while the Phase 4 tray lifecycle is lazy/restartable.

No broad swallowing or unrelated implementation change was added to mask these failures.

### Complete Windows-tray suite

Command:

```text
$env:PYTHONPATH = 'src'; & 'C:\Users\mhoem\AppData\Local\Temp\p\.venv\Scripts\python.exe' -m pytest --basetemp '.pytest-tmp-task7-all' tests/windows_tray -q
```

Result: 175 passed, 7 failed in 3.31s.

The seven failures are the four contract-test failures above plus these three existing baseline mismatches:

- `test_capture_worker_logs_safe_diagnostics_for_unexpected_exception` expects an older traceback format.
- `test_shutdown_logs_timeout_without_raising` does not observe the current guarded timeout diagnostic setup.
- `test_ensure_visible_recovers_when_icon_is_missing` expects a rebuild behavior not exercised by the current tray adapter contract.

### Compilation

Command equivalent using the available runtime:

```text
$env:PYTHONPATH = 'src'; & 'C:\Users\mhoem\AppData\Local\Temp\p\.venv\Scripts\python.exe' -m compileall -q src/piper/windows_tray
```

Result: PASS — exit code 0.

### Patch hygiene

Command:

```text
git diff --cached --check
```

Result: PASS — exit code 0.

## Self-review

- The stale-capture test uses a pre-resume generation and asserts no speech submission and no `last_text` mutation.
- The conflict test asserts the stable user-facing message, confirms shutdown has not begun, then verifies clean Exit requests teardown.
- The replay test asserts cancellation of generation 10, resume advancement to generation 11, and replay submission at generation 12.
- The test fixture string `must never be spoken` is local test data; it is not sent to a production logger.
- The new file does not duplicate Phase 5 packaging or manual acceptance coverage.
- The staged patch contains only the requested regression test; unrelated existing untracked files remain untouched.

## Concerns

The requested Task 7 file passes completely. Full required suite verification is limited by the repository’s existing seven baseline failures listed above, and the host lacks the configured Python 3.12 executable on PATH. The available fallback runtime is functional and compiled the tray modules successfully.
