# Phase 3 Task 4 Report

## Status

DONE

Task 4 is implemented in the current Piper branch. The scoped tests now prove that unrelated status and auxiliary failure paths remain visual/diagnostic only and do not submit error speech requests.

## Commit

- `test: lock down spoken error boundaries`

## Tests and command/output

Required command, run with the bundled Python runtime and a workspace-local pytest basetemp:

```text
C:\Users\mhoem\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "import sys; sys.path.insert(0,'src'); import pytest; raise SystemExit(pytest.main(['tests/windows_tray/test_error_sounds.py','tests/windows_tray/test_controller_speech.py','tests/windows_tray/test_phase3_replacement_flow.py','-q','--basetemp=.pytest-task4-basetemp']))"
```

Output:

```text
............................................                             [100%]
44 passed in 0.21s
```

`git diff --check` also completed without whitespace errors.

## Self-review

- Added the activation test with error sounds enabled; it preserves the exact already-running status and verifies empty notifications and worker submissions.
- Strengthened both foreground synthesis/playback failure tests with configured settings, a fake worker, generation 3, speaking state, existing status assertions, and empty worker submissions.
- Strengthened the failed disabled error-sounds toggle test with a fake worker and an empty submission assertion while preserving state, logging, and status assertions.
- Strengthened the voice replacement failure test with the existing fake worker and error sounds enabled; it preserves the visual status and rejects `SpeechPurpose.ERROR` submissions.
- Only the three scoped test files and this required report were staged for the commit. Existing unrelated working-tree changes were left untouched.

## Concerns

- The normal `pytest` executable was not relied on; verification used the repository's bundled Python runtime as requested.
- No production code was changed.
