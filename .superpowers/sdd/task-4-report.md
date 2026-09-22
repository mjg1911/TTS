# Phase 6 Task 4 Report

## Status

Implemented the offline frozen Kokoro Windows acceptance automation in:

- `script/accept_windows_kokoro_offline.ps1`

The Phase 5 smoke script did not require a change. It already accepts
`param([string]$PayloadRoot = "build/kokoro-payload")` and resolves the
worker and manifest paths from that parameter.

## Implementation

The acceptance script:

- Requires elevation with `#requires -RunAsAdministrator`.
- Resolves the already-built `PiperTray.exe` and never invokes Python or pip.
- Uses a per-process temporary LocalAppData/RoamingAppData root.
- Stops stale Kokoro workers and removes the isolated install root before the
  first launch.
- Blocks outbound traffic for both the tray executable and expected installed
  worker path before either executable starts.
- Verifies frozen tray deployment, then runs the installed worker smoke using
  `-PayloadRoot`.
- Corrupts `voices/af_heart.pt`, verifies the tray remains alive without a
  worker or automatic repair, and restores the voice in cleanup.
- Removes firewall rules, restores environment variables, and removes the
  temporary state root in `finally` cleanup blocks.

## Verification

- PowerShell AST parsing: PASS.
- Static structure checks for elevation, parameter, firewall setup/cleanup,
  installed-payload smoke, corrupt-asset rejection, and success marker: PASS
  (10 checks).
- Static check for Python/pip command invocations: PASS.
- Phase 5 smoke script comparison: no modification required or made.

The elevated Windows acceptance run was not executed. The current host is not
elevated, and the required frozen payload/build artifacts are unavailable:
`build/kokoro-payload` and `dist/KokoroWorker/KokoroWorker.exe` are absent.
The tray executable itself is present at `dist/PiperTray.exe`.

## Scope and concerns

Only the requested acceptance script and this report are task additions. The
working tree contained unrelated pre-existing changes; they were preserved and
not staged. The acceptance script must be run on an elevated Windows host after
the release tray and Kokoro payload have been built.
