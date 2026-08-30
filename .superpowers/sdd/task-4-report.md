# Task 4 Report

## Changed files

- `src/piper/windows_tray/speech.py`
- `tests/windows_tray/test_speech_worker.py`

The worker now types against `PlaybackPipeline`, creates one playback pipeline per speech request, preserves chunk streaming, publishes cancellation before stopping playback, and classifies context-manager finalization failures as `failure_phase='playback'`. The tests cover one pipeline across multiple chunks, playback cleanup classification, and stop-induced broken-pipe cancellation.

## Commit

- Message: `feat: route tray speech through pitch pipeline`

## Test command and output

Focused speech-worker verification with the bundled Python runtime:

```text
C:\Users\mhoem\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests/windows_tray/test_speech_worker.py -q
..........................                                               [100%]
26 passed in 2.79s
```

Combined focused verification:

```text
C:\Users\mhoem\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests/windows_tray/test_speech_worker.py tests/windows_tray/test_app_foundation.py -q
45 passed, 3 errors, 1 failed
```

## Concerns

- The combined run has three unrelated `test_app_foundation.py` `tmp_path` setup errors because the bundled runtime cannot scan `C:\Users\mhoem\AppData\Local\Temp\pytest-of-mhoem` (`WinError 5: Access is denied`).
- The same run has one unrelated existing `test_tk_thread_dispatches_activation_and_exit` failure caused by an extra hotkey-conflict status in the environment.
- Existing unrelated worktree changes were preserved and not staged.
