# Phase 6 Task 3 Report

## Status

Implemented and committed locally.

## Files

- Modified: `script/smoke_windows_tray.ps1`
- Report: `.superpowers/sdd/task-3-report.md`

The script change adds the specified isolated Kokoro deployment-target failure branch after the normal frozen-runtime smoke succeeds. It sets isolated LocalAppData and AppData roots, creates the `Piper/Kokoro` regular-file blocker, confirms PiperTray remains alive for three seconds, and restores/removes the branch-local state in `finally`. The existing frozen smoke process and outer setup/cleanup remain intact. The blocked branch uses a separate process variable so it cannot overwrite the normal smoke process handle.

## Commit

- Commit: `cf03936657548413d821b8d4f2373726beeae8d5`
- Message: `test: isolate Kokoro deployment failure from Piper`
- Commit content review: `git diff-tree --no-commit-id --name-only -r HEAD` reported only `script/smoke_windows_tray.ps1`.

## Tests and commands

1. `git diff --check`
   - Completed with no whitespace errors; Git emitted only its LF-to-CRLF working-copy warning.
2. PowerShell parser check using `[System.Management.Automation.Language.Parser]::ParseFile`
   - Output: `PowerShell parse passed`
3. `pwsh -File script/smoke_windows_tray.ps1`
   - Did not reach process startup. The existing prerequisite check stopped execution with:
     `Frozen smoke requires en_GB-alba-medium.onnx and its matching JSON in C:\PrOgram project\Piper`
   - Confirmed prerequisites: `dist/PiperTray.exe: True`; default voice model: `False`; default voice config: `False`.

## Self-review

- The new branch is placed only after the normal frozen-runtime readiness success.
- It blocks the Kokoro directory path with a regular file and does not move or delete the supported absent-root bootstrap location.
- It restores `LOCALAPPDATA` and `APPDATA` and removes only its isolated temporary roots.
- The existing Piper smoke voice setup, runtime cleanup, environment restoration, and SmokeRoot cleanup were not moved or removed.
- The commit contains only the requested script change; pre-existing unrelated worktree changes remain untouched.

## Concerns

- The full Windows smoke, including the new blocked-target runtime behavior, could not be exercised in this checkout because the required default voice files are absent. No claim is made that the end-to-end smoke passed.
- The shell profile also printed an unrelated `oh-my-posh` command-not-found message; it did not cause the script failure.

## Complete-review fix

### Findings addressed

- The normal frozen smoke process is now terminated with `taskkill.exe /PID ... /T /F` and waited on before the blocked branch launches, preventing the single-instance guard from turning the branch into a secondary no-op.
- The blocked branch now copies the existing isolated Piper voice model, voice JSON, and `settings.json` into its isolated `LOCALAPPDATA` and `APPDATA` roots before creating the `Piper\Kokoro` regular-file blocker.
- All blocked-branch setup is inside `try/finally`, so environment restoration, blocked-process tree termination/wait, and temporary-root cleanup run if setup fails.
- The blocked process uses the same process-tree termination and wait discipline as the normal smoke process.

### Validation commands and exact output

1. PowerShell parse check:

   Command:

   ```powershell
   $errors = $null
   [System.Management.Automation.Language.Parser]::ParseFile((Join-Path (Get-Location) 'script\smoke_windows_tray.ps1'), [ref]$null, [ref]$errors) | Out-Null
   if ($errors.Count -gt 0) { $errors | ForEach-Object { $_.Message }; exit 1 }
   ```

   Output:

   ```text
   PowerShell parse passed
   ```

2. Requested smoke command:

   Command:

   ```text
   pwsh -File script/smoke_windows_tray.ps1
   ```

   Output and status:

   ```text
   exit_code=1
   Exception: C:\PrOgram project\Piper\script\smoke_windows_tray.ps1:31
   Frozen smoke requires en_GB-alba-medium.onnx and its matching JSON in C:\PrOgram project\Piper
   ```

   The shell profile also emitted an unrelated `oh-my-posh` command-not-found message. The smoke did not reach process startup because the required voice files are absent.

3. Static smoke-branch validation:

   Command checked normal-process ordering, voice/config/settings copies, protected setup cleanup, and blocked-process tree termination.

   Output:

   ```text
   normal process is tree-terminated before blocked launch: True
   blocked branch copies voice model: True
   blocked branch copies voice config: True
   blocked branch copies settings: True
   blocked setup is protected by finally: True
   blocked process uses tree termination: True
   Static smoke-branch validation passed
   ```

## Fix status

The script fix is applied and remains uncommitted in the working tree. No files other than `script/smoke_windows_tray.ps1` and this report were changed by this fix. Full Windows runtime validation remains unavailable until the required voice model and matching JSON are present.

## Final commit

Commit:

```text
ac0bee25a43ca382d3f33712ed81e97cce5acb32
```

Message:

```text
test: isolate Kokoro deployment failure from Piper
```

Exact commit-path verification:

```text
commit_paths:
script/smoke_windows_tray.ps1
commit_stat:
ac0bee2 test: isolate Kokoro deployment failure from Piper
 script/smoke_windows_tray.ps1 | 36 +++++++++++++++++++++++++++++-------
 1 file changed, 29 insertions(+), 7 deletions(-)
```

Final validation outputs:

```text
PowerShell parse passed
normal process is tree-terminated before blocked launch: True
blocked branch copies voice model: True
blocked branch copies voice config: True
blocked branch copies settings: True
blocked process uses tree termination: True
Static smoke-branch validation passed
git diff --check passed
```

The final `pwsh -File script/smoke_windows_tray.ps1` invocation returned exit code 1 before process startup because `en_GB-alba-medium.onnx` and its matching JSON are absent from `C:\PrOgram project\Piper`. The shell also emitted the unrelated `oh-my-posh` command-not-found message.

## Task 3: Streamed sentence cancellation boundary

### Change

- Added `test_cancel_after_first_streamed_sentence_prevents_later_synthesis` to `tests/windows_tray/test_speech_worker.py`.
- The test cancels generation 305 synchronously from the player after the first sentence's audio reaches playback, then confirms the second sentence was never synthesized.
- No production source change was needed; the existing lazy generator checks cancellation immediately before each later sentence synthesis.

### Validation

Direct `pytest ... -q` could not start because `pytest` is not on the shell path. The same checks were run using the available `uv` launcher with its cache directed into the workspace:

Focused test:

```text
uv run --no-sync pytest tests/windows_tray/test_speech_worker.py::test_cancel_after_first_streamed_sentence_prevents_later_synthesis -q
.
1 passed in 0.20s
```

Selected cancellation tests:

```text
uv run --no-sync pytest tests/windows_tray/test_speech_worker.py::test_cancel_active_discards_matching_pending_request tests/windows_tray/test_speech_worker.py::test_cancellation_at_play_boundary_stops_player_before_chunk_is_played tests/windows_tray/test_speech_worker.py::test_cancellation_before_next_discards_chunk_without_advancing_synthesis tests/windows_tray/test_speech_worker.py::test_cancel_coordinates_with_blocked_play_boundary_without_deadlock tests/windows_tray/test_speech_worker.py::test_cancel_after_first_streamed_sentence_prevents_later_synthesis -q
.....
5 passed in 0.42s
```

### Commit

Pending local commit of `tests/windows_tray/test_speech_worker.py`; unrelated working-tree changes were left unstaged.
