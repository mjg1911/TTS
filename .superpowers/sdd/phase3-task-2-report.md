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

## Fix wave: reviewer Important findings

### Findings addressed

1. Added a dedicated play-entry boundary. The worker holds it across the final cancellation check and entry into `player.play()`. `cancel_active()` never waits on that boundary: it sets cancellation and calls the existing `AudioPlayer.stop()` directly, so blocked playback I/O remains interruptible. A cancellation that wins before playback entry is observed by the boundary and cannot invoke the player.
2. Added a cancellation check after all synthesis/playback error handling and immediately before terminal event emission, so cancellation wins over `FINISHED` even if it arrives during terminal selection.
3. Reset the failure phase to synthesis before every generator `next()`, preserving synthesis-failure classification when a later yield raises after earlier chunks have played.

### TDD regression evidence

Command after adding the three regression tests, before the production fix:

```text
$env:PYTHONPATH = 'src'; & 'C:\Users\mhoem\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/windows_tray/test_speech_worker.py -v
```

Result: `6 passed, 3 failed`. The three failures were the new play-boundary, terminal-cancellation, and later-synthesis-yield regressions.

### Fix verification

Focused worker command:

```text
$env:PYTHONPATH = 'src'; & 'C:\Users\mhoem\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/windows_tray/test_speech_worker.py -v
```

Result: `9 passed`.

Required covering worker/audio command:

```text
$env:PYTHONPATH = 'src'; & 'C:\Users\mhoem\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/windows_tray/test_speech_worker.py tests/windows_tray/test_audio_playback_cancel.py -q
```

Result: `12 passed`.

Additional verification:

```text
& 'C:\Users\mhoem\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m compileall -q src\piper\windows_tray\speech.py tests\windows_tray\test_speech_worker.py
git diff --check
```

Result: compilation passed and `git diff --check` passed. The only output was Git’s existing LF-to-CRLF working-copy warning.

### Fix self-review

- The boundary lock is not used by `cancel_active()` or `shutdown()` while stopping a player, so existing cancellable `AudioPlayer.play()` behavior is preserved.
- The regression tests force cancellation at the player-entry check and terminal-selection check, and verify no player entry or stale `FINISHED` event occurs.
- The later-yield test verifies that one already-played chunk does not change a subsequent synthesis exception into a playback failure.
- No unrelated production files were changed.

## Second fix wave: atomic cancellation boundaries

### Reviewer findings addressed

The worker now uses one reentrant decision boundary for both the final cancellation check plus `player.play()` entry and for terminal event selection plus emission. `cancel_active()` stops the active player before waiting on that boundary, which preserves the existing `AudioPlayer.stop()` behavior for blocked playback without holding a lock across the stop call. It then commits cancellation under the same boundary. Consequently, a cancellation either wins before playback/terminal selection or linearizes after that operation; it cannot be inserted into either gap.

Shutdown follows the same stop-before-boundary ordering, keeps condition notification intact, skips self-join, and remains safe if invoked from an event callback.

### Deterministic TDD evidence

Two regression tests were added before the production change:

- `test_cancel_coordinates_with_blocked_play_boundary_without_deadlock` holds `player.play()` in progress, verifies `stop()` is reached while playback is blocked, verifies cancellation waits on the shared boundary, then releases playback and checks that one terminal event is produced.
- `test_cancel_coordinates_with_terminal_event_emission` blocks terminal event emission, starts cancellation, verifies cancellation waits for the shared boundary, then releases emission and checks the already-selected `FINISHED` result remains the sole terminal event.

Pre-fix focused command:

```text
$env:PYTHONPATH = 'src'; & 'C:\Users\mhoem\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/windows_tray/test_speech_worker.py -v
```

Result: `9 passed, 2 failed`; both failures were the new boundary-coordination regressions.

### Fix verification

Focused worker command:

```text
$env:PYTHONPATH = 'src'; & 'C:\Users\mhoem\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/windows_tray/test_speech_worker.py -v
```

Result: `11 passed`.

Required covering worker/audio command:

```text
$env:PYTHONPATH = 'src'; & 'C:\Users\mhoem\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/windows_tray/test_speech_worker.py tests/windows_tray/test_audio_playback_cancel.py -q
```

Result after correcting the test’s expected linearization outcome: `14 passed`.

Additional verification:

```text
& 'C:\Users\mhoem\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m compileall -q src\piper\windows_tray\speech.py tests\windows_tray\test_speech_worker.py
git diff --check
```

Result: compilation passed and `git diff --check` passed. Git emitted only its existing LF-to-CRLF working-copy warnings.

### Second-wave self-review

- `cancel_active()` and `shutdown()` stop players before acquiring the shared decision boundary, preventing lock inversion with blocked `AudioPlayer.play()` I/O.
- Playback entry and terminal event emission each hold the same boundary through their externally visible operation.
- Cancellation may lose only when the worker has already atomically entered playback or terminal emission; that ordering is covered by the deterministic tests.
- Existing synthesis/playback failure classification, stale-chunk suppression, latest-pending replacement, and five-second shutdown behavior remain covered by the full worker suite.
