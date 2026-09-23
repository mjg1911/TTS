# Manual Kokoro integrity verification — Task 2 report

## Changes

- Automatic bundled payload deployment and tray preparation now use structural inspection, comparing manifest bytes to decide whether a bundle needs deployment.
- Worker initialization now inspects the installation structure and checks the supplied manifest fingerprint without hashing model and voice files.
- Payload tests cover a no-hash no-op, preserving same-manifest corrupt bytes for manual verification, and rejection of a bundle missing a required file.
- Worker protocol tests cover initialization without invoking the full verifier.

## TDD evidence

RED: Before production changes, the focused payload and worker tests failed as expected: payload no-op invoked `_sha256`, same-manifest corruption raised a hash mismatch, and worker tests could not find the structural inspection entry point. Result: 9 failed, 4 passed.

GREEN: After production changes and adapting the response-error test to permit existing diagnostic fields, the required focused command passed: 24 passed.

Command used for both runs:

```text
.venv\Scripts\python.exe -m pytest tests/test_kokoro_assets.py tests/windows_tray/test_kokoro_payload.py tests/windows_tray/test_kokoro_worker_protocol.py -q --basetemp .pytest-task2-temp
```

## Worker main.py handling

The existing diagnostics edits in `src/piper/kokoro_worker/main.py` were preserved. The intended Task 2 hunks in that file are only:

- Import `inspect_kokoro_installation` instead of `verify_kokoro_installation`.
- Use `inspect_kokoro_installation(root)` in the `initialize` branch.

Do not stage or commit this file as part of Task 2; these two lines remain mixed with the pre-existing diagnostics changes for selective integration.

## Commit scope

Task 2 changes in the other scoped files are committed separately. All other pre-existing working-tree changes remain untouched.
