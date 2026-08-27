# Phase 3 Task 3 Report

## Status

Implemented the controller playback state machine on `Phase-3`.

## Scope

Changed only the Task 3 implementation and test files:

- `src/piper/windows_tray/commands.py`
- `src/piper/windows_tray/controller.py`
- `tests/windows_tray/test_controller_speech.py`

## Requirements implemented

- Added `PlaybackState.IDLE`, `SPEAKING`, `STOPPED`, and `SHUTTING_DOWN`.
- Added monotonic `speech_generation` tracking.
- Added `STOP_REQUEST`, `REPLAY_REQUEST`, and `WORKER_EVENT` commands.
- Serialized worker output through `enqueue_worker_event`; the callback only queues a command and does not mutate state or access audio playback.
- A capture request while speaking cancels the active generation, invalidates it, enters `STOPPED`, and starts capture.
- A current successful capture replaces `last_text`, creates a new generation, enters `SPEAKING`, and submits a `SpeechRequest`.
- A failed replacement capture enters `STOPPED` without replaying the prior text.
- `CANCEL_REQUEST` and `STOP_REQUEST` cancel only active speech; idle/stopped requests are no-ops.
- Replay cancels active speech when necessary, creates a new generation, and submits the unchanged `last_text`.
- Matching worker events transition to `IDLE`/`STOPPED`; stale generations are ignored.
- Matching worker failures log the worker detail and show a concise status message.
- Exit transitions to `SHUTTING_DOWN`, shuts down the speech worker, and gates replay.
- Existing Phase-2 capture behavior remains intact.

## TDD evidence

The new test module was written before the implementation. The initial RED run could not collect because the new `PlaybackState` API was not yet present. After implementation, the focused test module passed. One assertion was corrected after observing that a replacement capture correctly starts a second capture job immediately.

## Verification

Using the bundled workspace Python runtime with `PYTHONPATH=src`:

- `pytest tests/windows_tray/test_controller_speech.py -q`: 9 passed.
- `pytest tests/windows_tray/test_controller_foundation.py tests/windows_tray/test_controller_capture.py tests/windows_tray/test_controller_speech.py tests/windows_tray/test_speech_worker.py -q`: 35 passed.
- `python -m py_compile src/piper/windows_tray/commands.py src/piper/windows_tray/controller.py tests/windows_tray/test_controller_speech.py`: passed.
- `git diff --check`: passed; Git reported only normal LF-to-CRLF conversion warnings for the two modified source files.

The complete `tests/windows_tray` run was also attempted. It reported 101 passed, 11 failed, and 16 errors. The failures/errors are outside the Task 3 files and include pytest temporary-directory permission errors, existing app-test logger fixture mismatches, and capture fixture exhaustion. The Task 3 focused/regression set passed independently.

## Review Fix: Pending Speech Cancellation

The review finding was reproducible: when an active request occupied the worker and the controller advanced to a newer generation, `SpeechWorker.cancel_active()` returned because the requested generation was not active, leaving the matching pending request queued. That request could then play after cancellation.

The fix updates `SpeechWorker.cancel_active()` to discard a pending request with the cancelled generation while retaining the existing active-player cancellation behavior. A regression test holds active generation 14, queues generation 15, cancels generation 15, and verifies that only generation 14 plays and no generation-15 event is emitted.

Review-fix verification:

- RED: `test_cancel_active_discards_matching_pending_request` failed because the stale pending audio played.
- GREEN: the focused regression and controller speech tests passed: 10 passed.
- Covering controller/worker suite after the fix: 36 passed.
- Focused syntax compilation and `git diff --check`: passed.

## Commit

`feat: serialize tray speech state transitions`
