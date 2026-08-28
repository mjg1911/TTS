# Windows Tray Smoke Cleanup Design

## Problem

The frozen Windows tray smoke test successfully reaches the tray event loop, but its `finally` block can fail while deleting the isolated temporary root. `Stop-Process -Force` may return before the tray process has fully released the file handle for `piper-tray.log`.

## Scope

Change only `script/smoke_windows_tray.ps1`. The tray application's runtime and logging lifecycle remain unchanged.

## Design

The cleanup sequence will:

1. Stop the spawned tray process when it is still running.
2. Wait for the process to report that it has exited, with a bounded timeout.
3. Retry recursive deletion of the isolated smoke root for a short bounded interval, allowing Windows time to release the log handle.
4. Re-throw the final deletion error if cleanup still cannot complete.

Environment restoration remains in the cleanup path regardless of process or deletion outcome. No unbounded sleeps or silent cleanup failures will be added.

## Testing

Extend the packaging contract test to require the cleanup contract: process-exit waiting and bounded deletion retry around `$SmokeRoot`. Run the focused Windows-tray packaging tests and the broader Windows-tray test suite.

## Success Criteria

- A frozen-runtime smoke run does not fail solely because `piper-tray.log` is briefly locked after forced process termination.
- Cleanup remains bounded and reports a genuine persistent deletion failure.
- Existing startup/readiness checks and environment restoration are preserved.
