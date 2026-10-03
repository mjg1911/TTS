# Chatterbox Custom Voice Implementation Plan

> **For agentic workers:** Use subagent-driven-development to implement and review the tasks.

**Goal:** Import and persist a reference clip and toggle Chatterbox between custom and bundled voices.

**Architecture:** Copy validated WAV clips into a managed user directory. Carry the enabled reference path through transactional backend preparation into worker initialization; prepare conditionals before reporting ready.

**Tech Stack:** Python, tkinter, framed worker protocol, pinned Chatterbox Nano.

## Global Constraints

- Stay on branch Chatterbox.
- Preserve existing untracked user files.
- Reference clips must exceed five seconds.
- Invalid imports and failed preparation preserve the working voice and saved settings.
- Default voice and older saved settings remain compatible.
- Save both imported clip and toggle across restarts.

### Task 1: Local reference storage and worker support

Files: new `src/piper/windows_tray/chatterbox_voice.py`, `src/piper/windows_tray/nano_client.py`, `src/piper/nano_worker/main.py`, `src/piper/nano_worker/runtime.py`, and focused tests.

Interface: `import_reference_clip(source: Path, directory: Optional[Path] = None) -> Path` validates PCM WAV data and copies to a unique managed file. `NanoWorkerClient(..., reference_clip=None)` sends the reference only when enabled; worker prepares conditionals before ready. Initialization without a reference retains existing behavior.

- [x] Write tests for copied clips, short/corrupt clips, custom initialization and failed readiness.
- [x] Run `.venv/Scripts/python.exe -m pytest` with the new tests and confirm missing behavior failures.
- [x] Implement the helper and optional reference initialization.
- [x] Run new tests and `tests/windows_tray/test_nano_runtime.py`.

### Task 2: Options, persistence and transactional integration

Files: `settings.py`, `settings_window.py`, `controller.py`, `app.py` under `src/piper/windows_tray/`, and focused tests.

Interfaces: settings and snapshots add `chatterbox_custom_voice_enabled: bool = False` and `chatterbox_reference_clip: str = ""`. `apply_settings` receives both as optional keyword parameters. `nano_preparation_reference_clip()` returns the enabled reference or None. `_prepare_nano_backend(..., reference_clip=None)` passes it to the client. Reprepare when enabled/path changes, using the existing cancellation and rollback pattern.

- [x] Write tests for round trips, defaults, invalid values, toggle changes and rejected saves.
- [x] Run tests and confirm missing behavior failures.
- [x] Add Import reference clip, filename, instructions and Use custom voice in the Chatterbox frame; carry choices through background Apply and snapshot refresh.
- [x] Wire saved startup choices and transactional settings apply.
- [x] Run settings, Chatterbox device, integration and window tests.

### Task 3: Review and completion

- [x] Review the complete diff against the approved design and correct defects.
- [x] Run the Windows tray and worker test suites; inspect results.
- [x] Update user documentation with WAV import and duration requirements.
- [x] Commit only feature files on the current branch.

## Verification

- Full Windows tray suite: 877 passed, 2 skipped.
- Real source-worker GPU smoke: default, imported custom, default all generated non-silent audio.
- Real Tk layout checked at 900x680 with a long reference filename.
- Independent task and whole-feature review: no blocking findings.
- Existing packaged installations require the updated Nano worker; no packaged application rebuild was requested.
