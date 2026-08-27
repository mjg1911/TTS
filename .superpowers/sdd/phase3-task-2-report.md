# Phase 3 Task 2 Handoff Report

## Result

Implemented a daemon-thread speech coordinator with generation-tagged requests and events. It keeps synthesis and playback off the tray/controller thread, retains only the latest pending request, cancels matching active generations, stops active playback, suppresses cancelled chunks, and emits exactly one terminal event per started request.

## Files changed

- `src/piper/windows_tray/speech.py`
  - Added `SpeechEventKind`, `SpeechRequest`, `SpeechEvent`, and `SpeechWorker`.
  - Added condition-protected pending/active state, cancellation, active-player stopping, and five-second shutdown joining.
  - Uses the current voice provider and the voice sample rate to construct `AudioPlayer` instances.
  - Sanitizes synthesis and playback failures to generic user-facing event text; request text is never logged.
- `tests/windows_tray/test_speech_worker.py`
  - Covers start/finish, cancellation and stale-chunk suppression, synthesis failure, playback failure, latest pending replacement, and shutdown.
- `.superpowers/sdd/phase3-task-2-report.md`
  - This handoff report.

## TDD and verification

Tests were written before production implementation. The first attempts to run them were blocked by the shell missing `pytest`, then by the bundled runtime missing `onnxruntime`; after installing the missing test/runtime dependencies, the focused suite ran and exposed the synthesis/playback error-classification defect. That defect was fixed and the focused suite was rerun.

Focused command:

```text
$env:PYTHONPATH = 'src'; & 'C:\Users\mhoem\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/windows_tray/test_speech_worker.py -v
```

Result: `6 passed`.

Covering command:

```text
$env:PYTHONPATH = 'src'; & 'C:\Users\mhoem\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/windows_tray/test_speech_worker.py tests/windows_tray/test_audio_playback_cancel.py -q
```

Result: `9 passed`.

Additional syntax compilation for both new Python files passed.

The broader `tests/windows_tray` run produced `87 passed`, `11 failed`, and `16 errors`. The failures/errors are outside Task 2 and are attributable to existing tray/capture expectations plus the restricted temp-directory environment; no Task 2 test failed in that run.

## Self-review

- Scope is limited to the two requested implementation/test files plus this requested report.
- The worker has one daemon coordinator thread and one pending request slot; submitting replaces only pending work.
- Cancellation is generation-matched, sets the event before stopping the player, checks cancellation around synthesis yields and before playback, and gives cancellation precedence over failures.
- Each request emits `STARTED` and exactly one terminal event.
- Shutdown drops pending work, cancels/stops active work, notifies the condition, and joins for at most five seconds.
- No Tk calls, playback window, selected-text logging, or detailed exception text were added.

## Concerns

- The full Windows-tray suite remains non-green for unrelated pre-existing/environmental failures noted above. The Task 2 focused and audio-cancellation covering checks are green.
- The worker’s `player_factory` is injectable for tests and defaults to `AudioPlayer`; integration wiring into the controller is intentionally outside Task 2.
