# Phase 3 Task 5 Report

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
