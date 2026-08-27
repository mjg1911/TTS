# Phase 3 Task 5 Report

## Final Important-finding fix wave (2026-08-27)

### Findings addressed

- Restored the synchronous `CONFIGURE_VOICE` contract: the selected candidate is loaded in the controller command handler, and only a successfully loaded candidate is persisted and installed. Failed candidate loads leave the known-good voice and active speech unchanged.
- Added a controller state lock around tray snapshots and state transitions, preventing the tray thread from observing a partially updated snapshot.
- Shutdown now advances `speech_generation` and rejects all worker events after `SHUTTING_DOWN`, including events already queued before worker shutdown completed.
- `AudioPlayer.play()` now propagates `BrokenPipeError` and `OSError`; the speech worker classifies them as playback failures while its existing cancellation precedence remains intact.

### Regressions

- Synchronous voice candidate load and commit.
- Tray snapshot waits for the controller state lock.
- Shutdown generation invalidation and queued worker-event suppression.
- `BrokenPipeError`/`OSError` propagation from `AudioPlayer.play()`.
- Broken-pipe classification as a generic speech playback failure.

### Verification

Using the bundled workspace Python runtime with `PYTHONPATH=src`:

- TDD red run before production changes: 5 expected regression failures, 1 existing test passed.
- Focused controller/speech/audio/voice suite: **44 passed**.
- Full `tests/windows_tray` suite: **139 passed, 3 failed**.
- The three full-suite failures are pre-existing capture fixture/timeout failures in `tests/windows_tray/test_capture.py`, each ending in `StopIteration`; no changed Phase-3 test failed.
- The full suite used repository-local pytest basetemp because the default Windows temp directory is inaccessible in this environment.

## Status

Implemented on branch `Phase-3`.

## Delivered

- Wired the production `SpeechWorker` to `VoiceManager.current()` and controller worker-event delivery.
- Kept synthesis and playback off the Tk/tray thread, with explicit `ffplay` availability handling.
- Added dynamic tray `Stop speaking` and `Replay` actions backed by an immutable controller snapshot.
- Added stale worker-generation coverage for repeated capture replacement.
- Added stale voice-switch success and failure acceptance/rejection coverage.
- Preserved compatibility with existing tray test doubles and ensured worker shutdown during app cleanup.

## Verification

- Focused Phase 3/app/controller/worker suite: `46 passed`.
- Full `tests/windows_tray` suite: `132 passed, 4 failed`.

## Concerns

- The four remaining Windows-tray failures are pre-existing outside Task 5: three capture tests exhaust their fake clipboard read iterator during retry polling, and one Task 4 foundation test assumes asynchronous voice switching completes synchronously.
- The requested `tests/test_piper.py` path does not exist in this checkout, so that command could not be run.
